"""AI 视频生成服务（Phase 6/7：Seedance 图片驱动视频分镜）。

核心原则：
- 视频生成模块独立于「解说词与分镜」页面；不使用 narration/visual_prompt/image_prompt 作为视频提示词来源。
- 用户必须明确选择首帧后才可发起图生视频；首尾帧必须明确选择两张图（顺序固定）。
- 每次生成保存完整参数快照（提示词、模板、首帧、尾帧、模型、结果版本）。
- 建筑强约束默认启用并保存到任务快照；冲突指令（增加楼层/改变轮廓/移动道路/替换主楼）阻止提交。
"""

from __future__ import annotations

import re
import time
import base64
import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.adapters.base import MockMixin
from app.adapters.factory import build_video_adapter, get_llm_adapter, get_video_adapter
from app.core.config import settings
from app.core.exceptions import AIProviderError, NotFoundError
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.video_segment import VideoSegment
from app.models.video_project import VideoProject
from app.models.project import Project
from app.models.video_generation import (
    VideoGenerationJob,
    VideoGenerationTemplate,
    VideoGenerationVersion,
)
from app.services.video_gen_templates import ARCH_CONSTRAINTS, ARCH_NEGATIVE, SYSTEM_TEMPLATES
from app.services.video_composer import probe_media
from app.services.construction_prompt import (
    CONSTRUCTION_MODE_PRESENTATION,
    construction_quality_checks,
    construction_transition_is_controlled,
    normalize_construction_recipe,
    compile_construction_prompt,
)

logger = get_logger(__name__)

SEEDANCE_PROMPT_LIMIT = 2000
CONSTRUCTION_PROMPT_RECOMMENDED_LIMIT = 800
CONSTRUCTION_AI_NEGATIVE = (
    "液体融化、透明蓝膜、发光扫描、粒子生长、科幻特效，"
    "结构整体变形、构件漂移闪烁、塔吊和道路移动、错误新增楼层、镜头跳切抖动"
)

# 分辨率属于任务参数，不应被提示词大师返回的自然语言覆盖。模型偶尔会
# 在镜头提示词里写入“4K/超高清”等描述，最终编译时统一移除，实际输出
# 由任务的 resolution 字段控制（例如页面选择的 720p）。
_PROMPT_RESOLUTION_TOKEN = r"(?:8k|4k|2k|1080p|720p|480p)"
_PROMPT_RESOLUTION_RE = re.compile(
    rf"(?:分辨率|清晰度)\s*(?:为|是|设为|设置为|[:：=])?\s*(?:{_PROMPT_RESOLUTION_TOKEN}|超高清|高清)(?:画质|分辨率)?"
    rf"|(?:{_PROMPT_RESOLUTION_TOKEN})\s*(?:画质|分辨率)?"
    r"|(?:超高清|高清)(?:画质|分辨率)",
    re.IGNORECASE,
)


def sanitize_prompt_resolution(text: str, *, resolution: str | None = None) -> str:
    """移除提示词中的分辨率描述，让高级参数成为唯一输出规格来源。"""
    value = (text or "").strip()
    if not value or not resolution:
        return value
    if not _PROMPT_RESOLUTION_RE.search(value):
        return value
    value = _PROMPT_RESOLUTION_RE.sub("", value)
    # 清掉替换后留下的空括号、重复标点和句首句尾标点。
    value = re.sub(r"[（(]\s*[）)]", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    value = re.sub(r"([，,；;。])\s*([，,；;。])+", r"\1", value)
    return value.strip(" ，,；;。")

# ---------------- 建筑约束冲突检测 ----------------

CONFLICT_PATTERNS = [
    (r"增加.*(楼层|层|建筑主体|高度)", "增加楼层/建筑主体/高度"),
    (r"(减少|删除|去掉|移除).*(楼层|层|建筑主体|主楼|塔楼)", "减少/删除楼层或建筑主体"),
    (r"(改变|修改).*(轮廓|体量|立面|层数|体形)", "改变建筑轮廓/体量/层数"),
    (r"(移动|改).*(道路|主入口|柱网|柱距)", "移动道路/主入口/柱网"),
    (r"(替换|换成|另建|重建成).*(主楼|建筑|塔楼|建筑主体)", "替换主楼/建筑"),
    (r"(改成|变为).*(不同|另一栋|别的|其他).*建筑", "更换为其它建筑"),
    (r"(增加|新建|添加).*(道路|主楼|建筑主体)", "新增道路/主楼/建筑主体"),
    (r"(推倒|拆除|重做)", "拆除/重做建筑"),
]


def check_arch_conflicts(text: str, recipe: dict | None = None) -> list[str]:
    """检测用户视频提示词中的结构修改冲突请求。"""
    if not text:
        return []
    conflicts = []
    for pattern, desc in CONFLICT_PATTERNS:
        # 施工演进模式允许在声明的起止状态和工序时间轴内逐步形成构件。
        # 仍然保留“替换建筑/改成另一栋建筑”等不可控结构变更的拦截。
        if construction_transition_is_controlled(recipe) and desc in {
            "增加楼层/建筑主体/高度",
            "减少/删除楼层或建筑主体",
            "新增道路/主楼/建筑主体",
        }:
            continue
        if re.search(pattern, text):
            conflicts.append(desc)
    return conflicts


def build_final_prompt(
    *,
    positive_prompt: str,
    negative_prompt: str | None,
    constraints_enabled: bool,
    arch_constraints: list[str] | None,
) -> tuple[str, str]:
    """组合最终提交提示词：用户视频提示词 + 建筑强约束。

    约束默认启用；启用时追加到正向提示词末尾，并把负向约束合并到负向提示词。
    """
    positive = (positive_prompt or "").strip()
    constraints = list(arch_constraints if arch_constraints is not None else ARCH_CONSTRAINTS) if constraints_enabled else []

    positive_parts = [positive]
    if constraints:
        positive_parts.append("；".join(constraints))
    final_positive = "。".join(part for part in positive_parts if part and part.strip())

    negatives: list[str] = []
    if negative_prompt and negative_prompt.strip():
        negatives.append(negative_prompt.strip())
    if constraints:
        negatives.append(ARCH_NEGATIVE)
    final_negative = "，".join(dict.fromkeys(negatives))
    return final_positive, final_negative


def build_recipe_prompt(
    *,
    prompt: str,
    recipe: dict | None,
    construction_max_chars: int = 1400,
) -> str:
    """把模板配方的结构化字段展开成 Seedance 可直接理解的文本提示词。"""
    if not isinstance(recipe, dict):
        return (prompt or "").strip()

    normalized_recipe = normalize_construction_recipe(recipe)
    base_prompt = (prompt or "").strip()
    is_construction_v2 = bool(
        isinstance(normalized_recipe, dict)
        and normalized_recipe.get("recipe_version", 1) >= 2
    )
    # 高级施工配方已经包含工程动作、时序和镜头。快速生成页遗留的整段
    # “施工部署动画/时间轴/空间锚点”文本只会重复一次，直接跳过；短的
    # 用户意图（例如“突出钢筋节点细节”）仍然保留。
    legacy_recipe_words = (
        "施工时间轴",
        "摄影时间轴",
        "空间锚点",
        "工程事实",
        "状态转换",
        "负向约束",
        "施工部署动画",
    )
    drop_redundant_base = is_construction_v2 and (
        len(base_prompt) > 72 or any(word in base_prompt for word in legacy_recipe_words)
    )
    parts: list[str] = [] if drop_redundant_base else [base_prompt]
    construction_text = compile_construction_prompt(
        normalized_recipe,
        max_chars=construction_max_chars,
    )
    if construction_text:
        parts.append(construction_text)
    recipe = normalized_recipe or recipe
    is_construction_v2 = bool(
        construction_text
        and isinstance(recipe, dict)
        and recipe.get("recipe_version", 1) >= 2
    )
    camera = recipe.get("camera")
    if isinstance(camera, dict):
        camera_fields = [
            f"类型：{camera.get('type')}" if camera.get("type") else "",
            f"方向：{camera.get('direction')}" if camera.get("direction") else "",
            f"路径：{camera.get('path')}" if camera.get("path") else "",
            f"速度：{camera.get('speed')}" if camera.get("speed") else "",
            f"强度：{camera.get('intensity')}" if camera.get("intensity") else "",
        ]
        camera_text = "；".join(item for item in camera_fields if item)
    else:
        camera_text = str(camera or "").strip()
    if camera_text and not is_construction_v2:
        parts.append(f"运镜设定：{camera_text}")

    timeline = recipe.get("timeline")
    timeline_items: list[str] = []
    if isinstance(timeline, list):
        for item in timeline:
            if not isinstance(item, dict):
                continue
            instruction = str(item.get("instruction") or item.get("description") or "").strip()
            if not instruction:
                continue
            start = item.get("from", item.get("start", 0))
            end = item.get("to", item.get("end", 100))
            timeline_items.append(f"{start}%-{end}%：{instruction}")
    elif isinstance(timeline, str) and timeline.strip():
        timeline_items.append(timeline.strip())
    if timeline_items and not is_construction_v2:
        parts.append("时间轴：" + "；".join(timeline_items))

    reference_timing = recipe.get("reference_timing_seconds")
    if isinstance(reference_timing, list) and reference_timing:
        timing_items: list[str] = []
        for index, value in enumerate(reference_timing, 1):
            try:
                timing_items.append(f"第{index}张={float(value):.3f}s")
            except (TypeError, ValueError):
                continue
        if timing_items:
            duration = recipe.get("clip_duration_seconds")
            try:
                duration_text = f"，总时长{float(duration):.3f}s" if duration is not None else ""
            except (TypeError, ValueError):
                duration_text = ""
            parts.append(
                "参考图时序（从当前镜头起点0秒计算，不使用原视频绝对时间"
                f"{duration_text}）：" + "；".join(timing_items)
            )

    preserve = recipe.get("preserve")
    preserve_items = preserve if isinstance(preserve, list) else [preserve] if preserve else []
    preserve_items = [str(item).strip() for item in preserve_items if str(item).strip()]
    if preserve_items and not is_construction_v2:
        parts.append("建筑保持项（必须锁定）：" + "；".join(preserve_items))

    allow_change = recipe.get("allow_change")
    change_items = allow_change if isinstance(allow_change, list) else [allow_change] if allow_change else []
    change_items = [str(item).strip() for item in change_items if str(item).strip()]
    if change_items and not is_construction_v2:
        parts.append("允许变化项（仅限这些变化）：" + "；".join(change_items))

    return "。".join(item for item in parts if item)


def build_recipe_negative_prompt(*, negative_prompt: str | None, recipe: dict | None) -> str:
    """把模板负向提示词条目合并为 Seedance 的负向约束文本。"""
    values: list[str] = []
    if negative_prompt and str(negative_prompt).strip():
        values.append(str(negative_prompt).strip())
    recipe = normalize_construction_recipe(recipe)
    if isinstance(recipe, dict):
        negative = recipe.get("negative")
        if isinstance(negative, list):
            values.extend(str(item).strip() for item in negative if str(item).strip())
        elif negative and str(negative).strip():
            values.append(str(negative).strip())
    return "，".join(dict.fromkeys(values))


def compile_video_prompts(
    *,
    positive_prompt: str,
    negative_prompt: str | None,
    prompt_recipe: dict | None,
    constraints_enabled: bool,
    arch_constraints: list[str] | None = None,
    resolution: str | None = None,
) -> tuple[str, str, dict | None]:
    """唯一提示词编译入口：完整配方留快照，Seedance 文本按语义自动压缩。"""
    recipe = normalize_construction_recipe(prompt_recipe)
    manual_override = str((recipe or {}).get("provider_prompt_override") or "").strip()
    if manual_override:
        # 专家在第六步确认的最终文本拥有最高优先级；配方仍完整保留用于审计和验收。
        return sanitize_prompt_resolution(manual_override, resolution=resolution), "", recipe
    is_construction_v2 = bool(isinstance(recipe, dict) and recipe.get("recipe_version", 1) >= 2)
    effective_arch_constraints = arch_constraints
    if is_construction_v2:
        # 完整工程字段留在任务快照；模型侧只接收短动作指令，避免通用约束重复淹没主动作。
        effective_arch_constraints = []
    clean_positive = re.sub(r"[。；]{2,}", lambda match: match.group(0)[0], (positive_prompt or "").strip())
    expanded_negative = build_recipe_negative_prompt(
        negative_prompt=negative_prompt,
        recipe=recipe,
    )
    constraint_positive, anticipated_negative = build_final_prompt(
        positive_prompt="",
        negative_prompt=expanded_negative,
        constraints_enabled=constraints_enabled and not is_construction_v2,
        arch_constraints=effective_arch_constraints,
    )
    negative_suffix_cost = len("。负向约束（禁止出现）：") + len(anticipated_negative)
    fixed_cost = len(clean_positive) + len(constraint_positive) + negative_suffix_cost + 8
    construction_budget = max(360, min(520, SEEDANCE_PROMPT_LIMIT - fixed_cost))
    expanded_positive = build_recipe_prompt(
        prompt=clean_positive,
        recipe=recipe,
        construction_max_chars=construction_budget,
    )
    final_positive, final_negative = build_final_prompt(
        positive_prompt=expanded_positive,
        negative_prompt=expanded_negative,
        constraints_enabled=constraints_enabled and not is_construction_v2,
        arch_constraints=effective_arch_constraints,
    )
    final_positive = sanitize_prompt_resolution(final_positive, resolution=resolution)
    final_positive, final_negative = _fit_provider_prompt_budget(
        final_positive,
        final_negative,
        limit=SEEDANCE_PROMPT_LIMIT,
    )
    return final_positive, final_negative, recipe


def _fit_clauses(text: str, max_chars: int, *, separators: str) -> str:
    """按完整分句装入预算；用于极端超长输入的最后一道语义保护。"""
    text = re.sub(r"[。；]{2,}", lambda match: match.group(0)[0], (text or "").strip("。；， "))
    if len(text) <= max_chars:
        return text
    clauses = [item.strip() for item in re.split(f"[{re.escape(separators)}]", text) if item.strip()]
    selected: list[str] = []
    used = 0
    for clause in clauses:
        cost = len(clause) + (1 if selected else 0)
        if used + cost > max_chars:
            continue
        selected.append(clause)
        used += cost
    return "；".join(selected)


def _fit_provider_prompt_budget(
    positive_prompt: str,
    negative_prompt: str,
    *,
    limit: int,
) -> tuple[str, str]:
    """确保最终投喂不超限；优先保留正向施工顺序，负向约束按分句去重压缩。"""
    positive = (positive_prompt or "").strip()
    negative = (negative_prompt or "").strip()
    if len(build_provider_prompt(positive, negative, enforce_budget=False)) <= limit:
        return positive, negative

    positive = positive.strip("。； ")
    negative = negative.strip("。；， ")
    negative = _fit_clauses(negative, 220, separators="，；。")
    suffix_cost = len("。负向约束（禁止出现）：") + len(negative) if negative else 0
    positive_budget = max(300, limit - suffix_cost)
    positive = _fit_clauses(positive, positive_budget, separators="。")
    return positive, negative


def normalize_video_duration(value: Any, fallback: int = 5) -> int:
    """把推荐时长（支持 6-10 秒这类范围文本）归一化为 Seedance 整数秒。"""
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]
    if not numbers:
        return max(2, min(15, int(fallback)))
    selected = sum(numbers[:2]) / min(2, len(numbers))
    return max(2, min(15, int(round(selected))))


def build_reference_timing(
    *,
    clip_start_seconds: float | None,
    clip_end_seconds: float | None,
    reference_frame_times: list | None,
    generation_mode: str,
) -> dict[str, Any]:
    """把模板草稿中的原视频时间转换成从当前镜头起点开始的相对时序。"""
    try:
        start = float(clip_start_seconds or 0.0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(clip_end_seconds) if clip_end_seconds is not None else start
    except (TypeError, ValueError):
        end = start
    clip_duration = round(max(0.0, end - start), 3)

    if generation_mode == "image_to_video":
        return {"clip_duration_seconds": clip_duration, "reference_timing_seconds": [0.0]}
    if generation_mode == "first_last_frame_video":
        return {
            "clip_duration_seconds": clip_duration,
            "reference_timing_seconds": [0.0, clip_duration],
        }

    relative: list[float] = [0.0]
    for raw_value in reference_frame_times or []:
        try:
            value = round(float(raw_value) - start, 3)
        except (TypeError, ValueError):
            continue
        value = round(max(0.0, min(clip_duration, value)), 3)
        if value <= 0.0:
            continue
        if abs(relative[-1] - value) > 0.001:
            relative.append(value)
    # 多图模式的最后一张图对应镜头结束，兼容旧草稿只保存中间帧的情况。
    if abs(relative[-1] - clip_duration) > 0.001:
        relative.append(clip_duration)
    return {
        "clip_duration_seconds": clip_duration,
        "reference_timing_seconds": relative,
    }


# ---------------- 模板种子 ----------------

def seed_video_generation_templates(db: Session) -> None:
    """按名称 upsert 内置建筑视频模板。

    - 新系统模板自动新增；
    - 已存在的同名系统模板更新字段；
    - 不在新列表中的旧系统模板自动停用（is_enabled=False），不删除（保留任务快照引用）。
    """
    names = [t["name"] for t in SYSTEM_TEMPLATES]
    existing = (
        db.query(VideoGenerationTemplate)
        .filter(VideoGenerationTemplate.is_system.is_(True))
        .all()
    )
    by_name = {t.name: t for t in existing}
    # 停用不在新列表中的旧系统模板
    for t in existing:
        if t.name not in names and t.is_enabled:
            t.is_enabled = False
    # upsert
    for i, t in enumerate(SYSTEM_TEMPLATES):
        row = by_name.get(t["name"])
        if row is None:
            row = VideoGenerationTemplate(is_system=True, is_enabled=True, created_by="system")
            db.add(row)
        row.name = t["name"]
        row.description = t.get("description")
        row.applicable_modes = t["applicable_modes"]
        row.default_positive_prompt = t.get("default_positive_prompt")
        row.default_negative_prompt = t.get("default_negative_prompt") or ARCH_NEGATIVE
        row.recommended_duration = t["recommended_duration"]
        row.recommended_aspect_ratio = t["recommended_aspect_ratio"]
        row.recommended_resolution = t["recommended_resolution"]
        row.recommended_camera_motion = t.get("recommended_camera_motion")
        row.default_arch_constraints = t.get("default_arch_constraints") or ARCH_CONSTRAINTS
        row.source_template_id = t.get("source_template_id")
        row.is_enabled = True
        row.sort_order = i
    db.commit()


# ---------------- 任务创建 ----------------


def build_provider_prompt(
    positive_prompt: str,
    negative_prompt: str | None,
    *,
    enforce_budget: bool = True,
) -> str:
    """构造实际发送给视频 Provider 的单段文本，供预览和执行共用。"""
    positive = (positive_prompt or "").strip()
    negative = (negative_prompt or "").strip()
    if enforce_budget:
        positive, negative = _fit_provider_prompt_budget(
            positive,
            negative,
            limit=SEEDANCE_PROMPT_LIMIT,
        )
    if negative:
        return f"{positive}。负向约束（禁止出现）：{negative}".strip("。 ")
    return positive


def create_video_job(
    db: Session,
    *,
    project_id: str,
    generation_mode: str,
    first_frame_asset_id: str,
    last_frame_asset_id: str | None,
    reference_asset_ids: list[str] | None = None,
    template_id: str | None,
    positive_prompt: str,
    negative_prompt: str | None,
    duration: int,
    aspect_ratio: str,
    resolution: str,
    seed: int | None,
    generate_audio: bool,
    constraints_enabled: bool,
    idempotency_key: str | None,
    created_by: str,
    provider: str | None = None,
    model_name: str | None = None,
    variant_group_id: str | None = None,
    prompt_recipe: dict | None = None,
    structure_conflict_confirmed: bool = False,
) -> VideoGenerationJob:
    """创建视频生成任务（含完整参数快照与建筑约束快照）。"""
    # 读取模板默认约束（若模板存在）
    template_constraints: list[str] | None = None
    template: VideoGenerationTemplate | None = None
    if template_id:
        template = db.get(VideoGenerationTemplate, template_id)
        if template and template.is_enabled:
            template_constraints = template.default_arch_constraints or ARCH_CONSTRAINTS

    normalized_recipe = normalize_construction_recipe(prompt_recipe)
    effective_recipe = normalized_recipe if isinstance(normalized_recipe, dict) else (
        template.prompt_recipe if template and isinstance(template.prompt_recipe, dict) else None
    )
    effective_recipe = normalize_construction_recipe(effective_recipe)
    # 施工演进模式只有在声明状态转换后才允许受控形成构件，模板配方也必须参与校验。
    conflict_text = str((effective_recipe or {}).get("provider_prompt_override") or positive_prompt or "")
    conflicts = check_arch_conflicts(conflict_text, effective_recipe)
    if conflicts and not structure_conflict_confirmed:
        raise ValueError("检测到可能改变工程结构的请求：" + "、".join(conflicts) +
                         "。禁止增加楼层、改变建筑轮廓、移动道路或替换主楼等结构性修改。")
    arch_constraints = list(template_constraints or ARCH_CONSTRAINTS) if constraints_enabled else []
    # 预览与真实任务只编译一次，避免配方文本和建筑约束被重复拼接。
    final_positive, final_negative, effective_recipe = compile_video_prompts(
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        prompt_recipe=effective_recipe,
        constraints_enabled=constraints_enabled,
        arch_constraints=arch_constraints,
        resolution=resolution,
    )

    provider = (provider or "").strip().lower() or None
    # 新建视频任务当前只开放 Seedance；Mock 仅保留给本地演示与自动化测试。
    if provider and provider not in ("seedance", "mock"):
        raise ValueError("当前新建视频任务仅开放 Seedance，请刷新页面后重新提交。")
    if provider:
        adapter = build_video_adapter(provider)
        if adapter is None or not adapter.is_available():
            raise ValueError(
                f"视频 Provider「{provider}」未配置 API Key 或不可用，请在 .env 配置后重试。"
            )
        provider = adapter.provider
    else:
        adapter = get_video_adapter()
        if adapter.provider not in ("seedance", "mock"):
            adapter = build_video_adapter("seedance")
            if adapter is None or not adapter.is_available():
                raise ValueError("当前新建视频任务仅开放 Seedance，但尚未配置 Seedance API Key。")
        provider = adapter.provider

    provider_prompt = build_provider_prompt(final_positive, final_negative)
    if provider == "seedance" and len(provider_prompt) > SEEDANCE_PROMPT_LIMIT:
        raise ValueError(
            f"最终 Seedance 提示词为 {len(provider_prompt)} 字符，超过 {SEEDANCE_PROMPT_LIMIT} 字符安全上限。"
            "请精简施工配方后再提交；系统不会截断施工顺序或安全约束。"
        )

    model_defaults = {
        "seedance": settings.seedance_video_model,
    }
    final_model = (
        model_name
        or model_defaults.get(provider)
        or settings.ai_video_model
        or settings.seedance_video_model
    )

    parameter_snapshot = {
        "generation_mode": generation_mode,
        "first_frame_asset_id": first_frame_asset_id,
        "last_frame_asset_id": last_frame_asset_id,
        "reference_asset_ids": list(reference_asset_ids or []),
        "template_id": template_id,
        "user_prompt": positive_prompt or "",
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "seed": seed,
        "generate_audio": generate_audio,
        "constraints_enabled": constraints_enabled,
        "structure_conflict_confirmed": structure_conflict_confirmed,
        "architecture_constraints": arch_constraints,
        "provider": provider,
        "model_name": final_model,
        "variant_group_id": variant_group_id,
        "template_recipe": effective_recipe,
        "compiled_positive_prompt": final_positive,
        "compiled_negative_prompt": final_negative,
        "provider_prompt": (
            f"{final_positive}。负向约束（禁止出现）：{final_negative}".strip("。 ")
            if final_negative else final_positive
        ),
        "construction_mode": (
            effective_recipe.get("construction_mode")
            if isinstance(effective_recipe, dict) else CONSTRUCTION_MODE_PRESENTATION
        ),
        "reference_timing_seconds": (
            list(effective_recipe.get("reference_timing_seconds") or [])
            if isinstance(effective_recipe, dict) else []
        ),
        "clip_duration_seconds": (
            effective_recipe.get("clip_duration_seconds")
            if isinstance(effective_recipe, dict) else None
        ),
    }

    job = VideoGenerationJob(
        project_id=project_id,
        # AI video results are independent assets. Video engineering owns
        # the only binding through VideoSegment.visual_asset_id.
        storyboard_shot_id=None,
        generation_mode=generation_mode,
        first_frame_asset_id=first_frame_asset_id,
        last_frame_asset_id=last_frame_asset_id,
        reference_asset_ids=list(reference_asset_ids or []),
        variant_group_id=variant_group_id,
        template_id=template_id,
        positive_prompt=final_positive,
        negative_prompt=final_negative,
        architecture_constraints=arch_constraints,
        constraints_enabled=constraints_enabled,
        provider=provider,
        model_name=final_model,
        duration=duration,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        seed=seed,
        generate_audio=generate_audio,
        watermark=False,
        status="queued",
        progress=0,
        idempotency_key=idempotency_key,
        created_by=created_by,
        parameter_snapshot=parameter_snapshot,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------- 任务执行 ----------------

def run_video_job(job_id: str) -> dict[str, Any]:
    """执行视频生成任务主体。

    1. 标记 running，读取首/尾帧图片
    2. 校验能力（图生/首尾帧；Provider 不支持首尾帧时禁止降级）
    3. Seedance：创建任务 → 轮询 → 下载 MP4；Mock：同步 generate
    4. 保存结果 Asset → VideoGenerationVersion
    5. 更新任务状态、耗时、错误
    """
    from app.core.database import SessionLocal
    from app.services.ai_configuration import refresh_runtime_config_from_db

    refresh_runtime_config_from_db()

    db = SessionLocal()
    started = time.monotonic()
    try:
        job = db.get(VideoGenerationJob, job_id)
        if not job:
            raise RuntimeError("视频生成任务不存在")
        if job.status == "cancelled":
            return {"status": "cancelled"}

        job.status = "running"
        job.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        job.progress = 10
        job.error_message = None
        db.commit()

        mode = job.generation_mode
        # 读取首帧 / 尾帧（顺序固定 [first_frame, last_frame]）
        first_frame_bytes = _load_asset_bytes(db, job.first_frame_asset_id, "首帧")
        last_frame_bytes = _load_asset_bytes(db, job.last_frame_asset_id, "尾帧") if mode == "first_last_frame_video" else None
        reference_ids = list(job.reference_asset_ids or [])
        reference_bytes = [b for aid in reference_ids if (b := _load_asset_bytes(db, aid, "参考图"))]

        if mode == "image_to_video" and not first_frame_bytes:
            raise RuntimeError("图生视频必须选择首帧图片，未检测到首帧。")
        if mode == "first_last_frame_video" and (not first_frame_bytes or not last_frame_bytes):
            raise RuntimeError("首尾帧模式必须同时选择首帧与尾帧两张图片，不允许降级为普通图生视频。")
        if mode == "multi_reference_video" and len(reference_bytes) < 2:
            raise RuntimeError("多参考图模式至少需要两张可读取的参考图。")

        adapter = build_video_adapter(job.provider)
        if adapter is None or not adapter.is_available():
            raise RuntimeError(
                f"任务使用的视频 Provider「{job.provider}」当前不可用（未配置 API Key），无法执行。"
            )
        # 任务快照中的模型优先于全局默认，保证多参考图不会被旧的 Seedance 1.x 配置接管。
        if job.model_name and hasattr(adapter, "config"):
            adapter.config["model"] = job.model_name
        if mode == "image_to_video" and not adapter.supports("image_to_video"):
            raise RuntimeError(f"Provider「{job.provider}」不支持图生视频。")
        if mode == "first_last_frame_video" and not adapter.supports("first_last_frame_video"):
                raise RuntimeError(f"Provider「{job.provider}」不支持首尾帧视频，且不允许降级为普通图生视频。")
        if mode == "multi_reference_video" and not adapter.supports("multi_reference_video"):
            raise RuntimeError(f"Provider「{job.provider}」不支持多参考图视频。请使用 Seedance 2.0。")

        job.progress = 20
        db.commit()

        prompt = job.positive_prompt or ""
        # 视频接口没有统一的独立 negative_prompt 字段，
        # 因此把负向约束显式并入最终发送的文本，同时保留数据库中的独立字段供审计。
        provider_prompt = build_provider_prompt(prompt, job.negative_prompt)
        if job.parameter_snapshot is not None:
            job.parameter_snapshot = {
                **job.parameter_snapshot,
                "provider_prompt": provider_prompt,
            }
            db.commit()
        video_bytes: bytes | None = None
        provider_task_id: str | None = None

        if job.provider in ("seedance", "minimax"):
            # Seedance / MiniMax H3 三段式：创建任务 → 轮询 → 下载
            provider_task_id = adapter.create_generation_task(
                prompt=provider_prompt,
                first_frame_bytes=first_frame_bytes,
                last_frame_bytes=last_frame_bytes,
                reference_frame_bytes=reference_bytes,
                mode=mode,
                duration=job.duration,
                resolution=job.resolution,
                aspect_ratio=job.aspect_ratio,
                seed=job.seed,
                generate_audio=job.generate_audio,
                watermark=job.watermark,
            )
            job.provider_task_id = provider_task_id
            job.progress = 30
            db.commit()

            if job.provider == "seedance":
                poll_interval = max(float(settings.seedance_poll_interval), 0.0)
                wait_timeout = max(float(settings.seedance_video_timeout), 1.0)
            else:
                poll_interval = max(float(settings.minimax_video_poll_interval), 0.0)
                wait_timeout = max(float(settings.minimax_video_timeout), 1.0)
            deadline = time.monotonic() + wait_timeout
            video_url: str | None = None
            while time.monotonic() < deadline:
                result = adapter.get_task_status(str(provider_task_id))
                status = str(result.get("status") or "").lower()
                if status == "succeeded":
                    video_url = result.get("video_url")
                    break
                if status in ("failed", "expired", "cancelled"):
                    raise RuntimeError(
                        f"{job.provider} 视频任务{status}: {result.get('fail_reason') or '未知错误'}"
                    )
                job.progress = min(85, job.progress + 5)
                db.commit()
                time.sleep(poll_interval)
            if not video_url:
                raise RuntimeError(f"{job.provider} 视频生成超时（task_id={provider_task_id}）")
            video_bytes = adapter._download_video(str(video_url))
        else:
            # Mock：适配器自带同步流程
            video_bytes = adapter.generate(
                provider_prompt,
                duration=float(job.duration),
                first_frame_bytes=first_frame_bytes,
                resolution=job.resolution,
                seed=job.seed,
                mode=mode,
                reference_frame_bytes=reference_bytes,
            )

        if not video_bytes:
            raise RuntimeError("视频生成结果为空")

        job.progress = 90
        db.commit()

        # 保存结果 Asset
        result_key = f"projects/{job.project_id}/ai_video/{job.id}/result_{int(time.time())}.mp4"
        storage.save(result_key, video_bytes)
        try:
            media_info = probe_media(video_bytes, suffix=".mp4")
        except Exception:
            logger.warning("video_quality_probe_failed", job_id=job.id)
            media_info = {"decodable": True, "duration_seconds": float(job.duration), "fps": 0}
        if media_info.get("decodable") is False:
            raise RuntimeError("视频生成结果无法被 ffprobe 解码，已阻止进入版本中心。")
        duration_seconds = float(media_info.get("duration_seconds") or job.duration)
        quality_report = {
            "decodable": bool(media_info.get("decodable", True)),
            "duration_seconds": round(duration_seconds, 3),
            "requested_duration_seconds": float(job.duration),
            "fps": float(media_info.get("fps") or 0),
            "width": media_info.get("width"),
            "height": media_info.get("height"),
            "warnings": [],
        }
        recipe_snapshot = (job.parameter_snapshot or {}).get("template_recipe")
        engineering_checks = construction_quality_checks(recipe_snapshot)
        if engineering_checks:
            quality_report["engineering_review"] = {
                "status": "manual_required",
                "checks": engineering_checks,
                "note": "工程质检项已随任务保存，当前需要人工确认画面与图纸/施工方案一致。",
            }
        if quality_report["fps"] and quality_report["fps"] < 20:
            quality_report["warnings"].append("输出帧率低于 20fps，建议改用 24fps 工程预设或重新生成。")
        if abs(duration_seconds - float(job.duration)) > 0.6:
            quality_report["warnings"].append("实际时长与请求时长偏差超过 0.6 秒。")

        asset = Asset(
            project_id=job.project_id,
            name=(
                "视频模板试生成-" if (job.parameter_snapshot or {}).get("template_preview") else "AI视频-"
            ) + f"{job.generation_mode}-{job.id[:8]}",
            asset_type="video",
            source="ai_video",
            file_key=result_key,
            file_size=len(video_bytes),
            mime_type="video/mp4",
            duration_seconds=duration_seconds,
            generated_by=job.provider,
            prompt=prompt,
            is_ai_generated=True,
            ai_disclaimer=(
                "Mock Render：演示生成视频，禁止用于正式投标。"
                if job.provider == "mock"
                else "AI 生成视频仅用于视觉表达，工程信息以原始模型、图纸及施工方案为准。"
            ),
            meta={
                "is_mock": job.provider == "mock",
                "video_job_id": job.id,
                "quality_report": quality_report,
                "template_draft_id": (job.parameter_snapshot or {}).get("template_draft_id"),
                "template_preview": bool((job.parameter_snapshot or {}).get("template_preview")),
                "template_recipe": (job.parameter_snapshot or {}).get("template_recipe"),
                "category": "视频模板试生成" if (job.parameter_snapshot or {}).get("template_preview") else "AI视频生成",
            },
            tags=(
                ["AI视频", "视频模板试生成"]
                if (job.parameter_snapshot or {}).get("template_preview")
                else ["AI视频"]
            ),
        )
        db.add(asset)
        db.flush()

        # 版本号：重新生成会创建新任务，但同一 variant_group 仍连续显示 V1/V2/V3。
        # 锁住项目行，串行化跨任务的 variant_group 编号分配。
        db.query(Project).filter(Project.id == job.project_id).with_for_update().one()
        if job.variant_group_id:
            existing_version = (
                db.query(func.max(VideoGenerationVersion.version_number))
                .filter(VideoGenerationVersion.variant_group_id == job.variant_group_id)
                .scalar()
            )
        else:
            existing_version = (
                db.query(func.max(VideoGenerationVersion.version_number))
                .filter(VideoGenerationVersion.video_job_id == job.id)
                .scalar()
            )
        version_number = int(existing_version or 0) + 1
        version = VideoGenerationVersion(
            video_job_id=job.id,
            result_asset_id=asset.id,
            version_number=version_number,
            variant_group_id=job.variant_group_id,
            provider=job.provider,
            model_name=job.model_name,
            seed=job.seed,
            generation_mode=job.generation_mode,
            prompt_snapshot={"prompt": job.positive_prompt},
            negative_prompt_snapshot={"prompt": job.negative_prompt},
            parameter_snapshot=job.parameter_snapshot,
            first_frame_asset_id=job.first_frame_asset_id,
            last_frame_asset_id=job.last_frame_asset_id,
            reference_asset_ids=list(job.reference_asset_ids or []),
            template_id=job.template_id,
        )
        db.add(version)

        job.result_asset_id = asset.id
        job.status = "success"
        job.progress = 100
        job.completed_at = time.strftime("%Y-%m-%d %H:%M:%S")
        job.elapsed_seconds = round(time.monotonic() - started, 2)
        db.commit()

        return {
            "status": "success",
            "asset_id": asset.id,
            "version_id": version.id,
            "file_key": result_key,
            "elapsed_seconds": job.elapsed_seconds,
            "quality_report": quality_report,
        }
    except Exception as exc:
        logger.exception("video_gen_job_failed", job_id=job_id)
        job = db.get(VideoGenerationJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)[:2000]
            job.completed_at = time.strftime("%Y-%m-%d %H:%M:%S")
            job.elapsed_seconds = round(time.monotonic() - started, 2)
            db.commit()
        raise
    finally:
        db.close()


def _load_asset_bytes(db: Session, asset_id: str | None, label: str) -> bytes | None:
    """读取素材文件字节；素材缺失时返回 None（由调用方决定是否报错）。"""
    if not asset_id:
        return None
    asset = db.get(Asset, asset_id)
    if not asset or not asset.file_key:
        return None
    try:
        return storage.load(asset.file_key)
    except Exception:
        logger.warning("video_gen_asset_load_failed", asset_id=asset_id, label=label)
        return None


# ---------------- 版本管理 ----------------

def select_version(db: Session, project_id: str, version_id: str, user_name: str) -> VideoGenerationVersion:
    """将某个版本设为当前结果（同一任务内取消其它版本选中）。"""
    version = db.get(VideoGenerationVersion, version_id)
    if not version or version.is_deleted:
        raise RuntimeError("视频版本不存在")
    job = db.get(VideoGenerationJob, version.video_job_id)
    if not job or job.project_id != project_id:
        raise RuntimeError("视频任务不存在或不属于当前项目")

    selected_query = db.query(VideoGenerationVersion.id).join(
        VideoGenerationJob, VideoGenerationVersion.video_job_id == VideoGenerationJob.id
    ).filter(VideoGenerationVersion.is_selected.is_(True))
    if job.variant_group_id:
        selected_query = selected_query.filter(VideoGenerationJob.variant_group_id == job.variant_group_id)
    else:
        selected_query = selected_query.filter(VideoGenerationVersion.video_job_id == job.id)
    selected_ids = [row[0] for row in selected_query.all()]
    if selected_ids:
        db.query(VideoGenerationVersion).filter(VideoGenerationVersion.id.in_(selected_ids)).update(
            {"is_selected": False}, synchronize_session=False
        )
    version.is_selected = True
    version.selected_by = user_name
    version.selected_at = time.strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    db.refresh(version)
    return version


def soft_delete_version(db: Session, project_id: str, version_id: str, user_name: str) -> None:
    """删除未被视频工程分段使用的视频版本。"""
    version = db.get(VideoGenerationVersion, version_id)
    if not version:
        raise RuntimeError("视频版本不存在")
    job = db.get(VideoGenerationJob, version.video_job_id)
    if not job or job.project_id != project_id:
        raise RuntimeError("视频任务不存在或不属于当前项目")
    if version.result_asset_id and db.query(VideoSegment.id).filter(
        VideoSegment.visual_asset_id == version.result_asset_id,
        VideoSegment.video_project_id.in_(
            db.query(VideoProject.id).filter(VideoProject.project_id == project_id)
        ),
    ).first():
        raise RuntimeError("该视频已被视频工程分段使用，请先解除分段引用再删除")
    version.is_deleted = True
    version.deleted_by = user_name
    version.deleted_at = time.strftime("%Y-%m-%d %H:%M:%S")
    db.commit()


# ---------------- 提示词大师（AI 读参考帧生成视频提示词） ----------------

def _mock_prompt_master(*, generation_mode: str, intent: str | None, template_default: str) -> str:
    """Mock / LLM 不可用时返回确定性的演示提示词。"""
    base = (template_default or "").strip()
    if not base:
        if generation_mode == "first_last_frame_video":
            base = (
                "严格保持首帧中建筑的主体数量、体量、轮廓、层数、道路、主入口和主要构件关系不变。"
                "镜头以稳定的鸟瞰视角缓慢推进，画面从首帧自然过渡到尾帧所示的建成效果，"
                "材质、光影、绿化与环境细节逐步呈现，过渡自然，写实工程渲染质感。"
            )
        else:
            base = "镜头缓慢向建筑主体推进，建筑稳定居中，光影自然，环境真实，画面平稳，写实工程渲染质感。"
    if intent and intent.strip():
        base = f"{base} 用户意图补充：{intent.strip()}"
    return base


def _default_prompt_recipe(
    *,
    prompt: str,
    negative_prompt: str,
    generation_mode: str,
    intent: str | None = None,
) -> dict[str, Any]:
    """LLM 不可用时仍返回可编辑的模板配方。"""
    construction_intent = bool(
        re.search(r"施工|工序|浇筑|绑扎|模板|钢筋|吊装|开挖|混凝土|机电安装|幕墙", intent or "")
    )
    return {
        "recipe_version": 2,
        "construction_mode": "construction_evolution" if construction_intent else "presentation",
        "category": "建筑外景运镜",
        "tags": ["建筑展示", "稳定运镜"],
        "generation_modes": [generation_mode],
        "camera": {
            "type": "orbit" if generation_mode == "first_last_frame_video" else "dolly_in",
            "direction": "clockwise",
            "path": "arc" if generation_mode == "first_last_frame_video" else "straight",
            "speed": "slow",
            "intensity": "low",
        },
        "timeline": [
            {"from": 0, "to": 20, "instruction": "保持首帧构图，镜头开始缓慢移动"},
            {"from": 20, "to": 80, "instruction": "保持建筑主体稳定，呈现自然空间变化"},
            {"from": 80, "to": 100, "instruction": "平稳到达尾帧构图并减速定格"},
        ],
        "preserve": list(ARCH_CONSTRAINTS[:5]),
        "allow_change": ["轻微光影变化", "树木、云层、人物和车辆的自然微动"],
        "negative": [negative_prompt],
        "prompt": prompt,
        "intent": (intent or "").strip(),
        "recommended": {"duration": 5, "aspect_ratio": "adaptive", "resolution": "720p"},
        "project_facts": {"structure_type": "", "current_stage": "", "target_stage": "", "fact_sources": []},
        "construction_unit": {"wbs_code": "", "work_item": "", "work_zone": "", "zone_mappings": [], "objects": [], "prerequisites": [], "completion_state": []},
        "state_transition": {"start_state": "", "end_state": "", "allowed_changes": [], "forbidden_jumps": []},
        "construction_timeline": [
            {"from": 0, "to": 20, "instruction": "确认前置条件与作业面，保持已完成构件稳定"},
            {"from": 20, "to": 80, "instruction": "按照声明的施工顺序推进一个主工序"},
            {"from": 80, "to": 100, "instruction": "完成目标状态并停止结构变化"},
        ],
        "camera_timeline": [
            {"from": 0, "to": 20, "instruction": "固定机位建立全景，交代作业区与空间锚点"},
            {"from": 20, "to": 80, "instruction": "保持轴线和焦段稳定，缓慢跟随施工工作面"},
            {"from": 80, "to": 100, "instruction": "减速定格目标状态，不切镜"},
        ],
        "spatial_anchors": list(ARCH_CONSTRAINTS[:3]),
        "temporary_works": {"required": [], "forbidden": []},
        "safety_constraints": ["临边防护连续", "人员佩戴安全帽和反光背心"],
        "quality_constraints": ["施工顺序符合前置关系", "已完成构件不得消失、漂移或重新生成"],
        "acceptance_checks": ["构件数量与位置一致", "施工顺序连续", "安全设施完整"],
    }


def _recipe_list(value: Any, *, split_text: bool = True) -> list[str]:
    """把视觉模型返回的字符串/数组统一为可编辑的条目列表。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        if split_text:
            parts = re.split(r"[；;、,，\n]+", value)
            normalized = [part.strip() for part in parts if part.strip()]
            return normalized or [value.strip()]
        return [value.strip()]
    return []


def _normalize_prompt_recipe(
    raw_recipe: Any,
    *,
    structured: dict[str, Any],
    prompt: str,
    negative_prompt: str,
    generation_mode: str,
    intent: str | None,
) -> dict[str, Any]:
    """保证 AI 返回的配方始终具备前端可展示的结构化字段。

    视觉模型有时会把 timeline、camera、preserve 等字段压缩成字符串，
    或把 recommended 生成为数组。这里统一为模板编辑器使用的稳定结构，
    不改变模型的核心内容，只补齐缺失的阶段和字段。
    """
    defaults = _default_prompt_recipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        generation_mode=generation_mode,
        intent=intent,
    )
    recipe = dict(raw_recipe) if isinstance(raw_recipe, dict) else {}
    for key in (
        "camera", "timeline", "preserve", "allow_change", "negative", "recommended",
        "construction_mode", "project_facts", "construction_unit", "state_transition",
        "construction_timeline", "camera_timeline", "spatial_anchors", "temporary_works",
        "safety_constraints", "quality_constraints", "acceptance_checks",
    ):
        if not recipe.get(key) and structured.get(key):
            recipe[key] = structured[key]

    camera_value = recipe.get("camera")
    if isinstance(camera_value, dict):
        camera = dict(camera_value)
    elif camera_value:
        camera = {"type": str(camera_value).strip()}
    else:
        camera = dict(defaults["camera"])
    camera.setdefault("type", "稳定运镜")
    camera.setdefault("direction", "")
    camera.setdefault("path", "")
    camera.setdefault("speed", "平稳")
    camera.setdefault("intensity", "低")

    timeline_value = recipe.get("timeline")
    timeline: list[dict[str, Any]] = []
    if isinstance(timeline_value, list):
        for item in timeline_value:
            if not isinstance(item, dict):
                continue
            start = item.get("from", item.get("start", item.get("start_percent", 0)))
            end = item.get("to", item.get("end", item.get("end_percent", 100)))
            instruction = item.get("instruction") or item.get("description") or item.get("prompt")
            if instruction:
                try:
                    start = max(0, min(100, float(start)))
                    end = max(start, min(100, float(end)))
                except (TypeError, ValueError):
                    start, end = 0, 100
                timeline.append({"from": start, "to": end, "instruction": str(instruction).strip()})
    elif isinstance(timeline_value, str) and timeline_value.strip():
        timeline = [
            {"from": 0, "to": 20, "instruction": "建立首帧构图，锁定建筑主体与空间关系"},
            {"from": 20, "to": 80, "instruction": timeline_value.strip()},
            {"from": 80, "to": 100, "instruction": "平稳过渡至尾帧并减速定格，保持结构连续"},
        ]
    if not timeline:
        timeline = list(defaults["timeline"])

    normalized = {
        **recipe,
        "recipe_version": recipe.get("recipe_version") or defaults["recipe_version"],
        "category": str(recipe.get("category") or defaults["category"]),
        "tags": _recipe_list(recipe.get("tags")) or list(defaults["tags"]),
        "generation_modes": _recipe_list(recipe.get("generation_modes"), split_text=False) or list(defaults["generation_modes"]),
        "camera": camera,
        "timeline": timeline,
        "preserve": _recipe_list(recipe.get("preserve")) or list(defaults["preserve"]),
        "allow_change": _recipe_list(recipe.get("allow_change")) or list(defaults["allow_change"]),
        "negative": _recipe_list(recipe.get("negative")) or list(defaults["negative"]),
        "prompt": prompt,
        "intent": (intent or "").strip(),
    }
    recommended_value = recipe.get("recommended")
    if isinstance(recommended_value, dict):
        recommended = dict(recommended_value)
    elif isinstance(recommended_value, str) and recommended_value.strip():
        recommended = {"duration": recommended_value.strip()}
    elif isinstance(recommended_value, list) and recommended_value:
        recommended = {"duration": str(recommended_value[0]).strip()}
    else:
        recommended = dict(defaults["recommended"])
    normalized["recommended"] = recommended
    return normalize_construction_recipe(normalized) or normalized


def _limit_prompt(text: str, max_chars: int = 500) -> str:
    """提示词长度以用户界面可编辑上限为准，尽量在句号/分号处完整截断。"""
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    cut = value[:max_chars]
    boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("，"), cut.rfind(" "))
    return (cut[:boundary] if boundary >= int(max_chars * 0.72) else cut).rstrip("，；。 ")


def generate_prompt_master(
    db: Session,
    project_id: str,
    *,
    first_frame_asset_id: str | None,
    last_frame_asset_id: str | None,
    middle_frame_asset_id: str | None = None,
    reference_asset_ids: list[str] | None,
    template_id: str | None,
    intent: str | None,
    generation_mode: str,
    reference_timing_seconds: list[float] | None = None,
    clip_duration_seconds: float | None = None,
    require_real_ai: bool = False,
) -> dict[str, Any]:
    """「提示词大师」：读取参考帧信息 + 用户意图，生成视频生成提示词。

    Kimi 多模态模型会收到参考帧原图；不支持视觉输入的历史文本模型则只使用参考帧名称/尺寸、
    模板默认提示词和用户意图作为上下文。最终正向提示词
    统一限制为 500 字符以内。Mock / 未配置 Key 时返回确定性的默认提示词，保证演示可运行。
    """
    ids = [i for i in (first_frame_asset_id, middle_frame_asset_id, last_frame_asset_id) if i] + list(reference_asset_ids or [])
    assets: list[Asset] = []
    for aid in dict.fromkeys(ids):  # 去重保序
        asset = db.get(Asset, aid)
        if asset and asset.project_id == project_id:
            assets.append(asset)
    if not assets:
        raise NotFoundError("未找到指定的参考帧图片")

    frame_lines = []
    for idx, a in enumerate(assets, 1):
        dim = f"{a.width}×{a.height}" if a.width and a.height else "尺寸未知"
        timing = ""
        if reference_timing_seconds and idx <= len(reference_timing_seconds):
            try:
                timing = f"，相对镜头时间 {float(reference_timing_seconds[idx - 1]):.3f}s"
            except (TypeError, ValueError):
                timing = ""
        frame_lines.append(f"{idx}. {a.name or '未命名'}（{dim}{timing}）")
    frames_text = "\n".join(frame_lines)
    timing_instruction = ""
    if reference_timing_seconds:
        timing_values: list[str] = []
        for index, value in enumerate(reference_timing_seconds, 1):
            try:
                timing_values.append(f"第{index}张={float(value):.3f}s")
            except (TypeError, ValueError):
                continue
        if timing_values:
            try:
                duration_text = (
                    f"，总时长 {float(clip_duration_seconds):.3f}s"
                    if clip_duration_seconds is not None else ""
                )
            except (TypeError, ValueError):
                duration_text = ""
            timing_instruction = (
                "参考图时序（必须按此顺序理解，从当前镜头起点 0 秒重新计算，"
                f"不使用原视频绝对时间{duration_text}）：" + "；".join(timing_values) + "\n"
            )

    template = db.get(VideoGenerationTemplate, template_id) if template_id else None
    template_default = (template.default_positive_prompt if template else "") or ""
    arch_hint = (
        "；".join(template.default_arch_constraints or [])
        if template and template.default_arch_constraints
        else "；".join(ARCH_CONSTRAINTS[:4])
    )
    negative = ARCH_NEGATIVE
    if template and template.default_negative_prompt:
        negative = f"{template.default_negative_prompt}；{ARCH_NEGATIVE}"

    mode_label = {
        "first_last_frame_video": "首尾帧视频（首帧→尾帧过渡）",
        "multi_reference_video": "多参考图视频（按参考图顺序构建镜头）",
    }.get(generation_mode, "图生视频（单张参考图）")
    intent_text = (intent or "").strip() or "无（由 AI 按参考帧自主拟定镜头与氛围）"

    adapter = get_llm_adapter("prompt_master")
    if isinstance(adapter, MockMixin):
        if require_real_ai:
            raise AIProviderError(
                "模板制作必须使用真实 AI。当前提示词大师没有生效的真实 Provider 或 API Key，"
                "请在 AI 配置中选择 Kimi 并保存有效的 Moonshot API Key 后重试。"
            )
        mock_prompt = sanitize_prompt_resolution(_mock_prompt_master(
            generation_mode=generation_mode,
            intent=intent,
            template_default=template_default,
        ), resolution="720p")
        mock_name = "建筑外景稳定运镜模板" if generation_mode == "first_last_frame_video" else "建筑外景展示模板"
        mock_description = (
            "适用于建筑外景的首尾帧连续镜头，保持建筑主体结构稳定，适合展示体量、立面与场地关系。"
            if generation_mode == "first_last_frame_video"
            else "适用于建筑外景展示，通过平稳推进镜头突出建筑主体、立面细节与整体空间关系。"
        )
        return {
            "prompt": mock_prompt,
            "name": mock_name,
            "description": mock_description,
            "negative_prompt": negative,
            "mode": "mock",
            "is_mock": True,
            "recipe": _default_prompt_recipe(
                prompt=mock_prompt,
                negative_prompt=negative,
                generation_mode=generation_mode,
                intent=intent,
            ),
        }

    user_msg = (
        "你是一名建筑工程投标视频的「提示词大师」。请根据以下参考帧与用户意图，"
        "为 AI 视频生成写一段精炼的中文提示词。\n"
        "要求：\n"
        "1. 明确镜头运动（如缓慢推进 / 环绕 / 固定微动 / 俯冲）；\n"
        "2. 保持建筑主体数量、体量、轮廓、层数、道路、主入口与主要构件关系不变；\n"
        "3. 若为首尾帧模式，说明首帧到尾帧的画面过渡方式与最终成片质感；\n"
        "4. 返回 JSON：name、description、prompt、negative_prompt、recipe、timeline、warnings、recommended_duration；不要 Markdown。\n"
        "name 是 12-24 字的中文模板名称，description 是 40-100 字的适用场景说明；名称和说明必须泛化样片中的具体建筑，不要写具体项目名。\n"
        "recipe 必须严格包含以下结构，不能把对象压缩成一句字符串："
        "category 字符串、tags 字符串数组、generation_modes 字符串数组；"
        "camera 对象 {type,direction,path,speed,intensity}；"
        "timeline 数组（至少 3 项，每项为 {from: 0-100, to: 0-100, instruction: 字符串}，覆盖首帧建立/中段变化/尾帧定格）；"
        "preserve 建筑保持项字符串数组；allow_change 可变化项字符串数组；negative 负向提示词字符串数组；"
        "recommended 对象 {duration,aspect_ratio,resolution}；"
        "施工视频必须额外返回 recipe_version=2、construction_mode（presentation 或 construction_evolution）、"
        "project_facts、construction_unit、state_transition、construction_timeline、camera_timeline、"
        "spatial_anchors、temporary_works、safety_constraints、quality_constraints、acceptance_checks。"
        "construction_timeline 描述工程状态变化，camera_timeline 描述摄影运动；"
        "若为 construction_evolution，必须明确 start_state、end_state、allowed_changes 和 forbidden_jumps，禁止跨工序跳变。\n\n"
        "5. prompt 必须控制在 500 个中文字符以内，优先保留镜头运动、主体约束和时序信息。\n\n"
        f"生成模式：{mode_label}\n"
        f"参考帧：\n{frames_text}\n"
        f"{timing_instruction}"
        f"用户意图：{intent_text}\n"
        f"可选模板默认提示词：{template_default or '无'}\n"
        f"必须保持的工程结构：{arch_hint}"
    )
    prompt = ""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    # 视觉模型要求 content 数组；把首帧、尾帧和多参考图按顺序送入模型。
    # 不支持视觉输入的历史文本模型只接收上面的文件名/尺寸元数据，不能假装看到了图片。
    vision_used = bool(getattr(adapter, "supports_vision", False))
    if vision_used:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_msg}]
        for idx, asset in enumerate(assets, 1):
            try:
                raw = storage.load(asset.file_key) if asset.file_key else b""
                if not raw:
                    continue
                mime = asset.mime_type or "image/jpeg"
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"},
                })
            except Exception:
                logger.warning("prompt_master_image_load_failed", asset_id=asset.id)
        messages = [{"role": "user", "content": content}]
    try:
        chat_kwargs: dict[str, Any] = {
            "temperature": 0.6,
            # 配方包含多个嵌套字段；800 tokens 容易在 recipe 中途截断。
            "max_tokens": 4000,
        }
        if str(getattr(adapter, "provider", "")).lower() == "kimi":
            # Kimi JSON Mode 让结构化配方保持可解析，避免模型只返回半截 JSON。
            chat_kwargs["response_format"] = {"type": "json_object"}
        prompt = adapter.chat(messages, **chat_kwargs)
    except Exception as exc:
        logger.exception("prompt_master_llm_error")
        if require_real_ai and isinstance(adapter, MockMixin):
            raise AIProviderError("真实 AI 调用失败，未生成模板配方，请检查提示词大师配置后重试。") from exc
        if not isinstance(adapter, MockMixin):
            error_text = str(exc)
            if "SDK 未安装" in error_text or "No module named 'volcenginesdkarkruntime'" in error_text:
                raise AIProviderError(
                    "火山方舟 SDK 未安装或当前后端环境未加载，请安装 volcengine-python-sdk[ark] 后重启后端。"
                ) from exc
            if "Image dimensions are too small" in error_text:
                raise AIProviderError("提示词大师参考帧尺寸过小，请重新提取关键帧后重试。") from exc
            if "401" in error_text or "Unauthorized" in error_text or "Authentication" in error_text:
                provider_name = str(getattr(adapter, "provider", "")).lower()
                if provider_name == "kimi":
                    adapter_config = getattr(adapter, "config", {}) or {}
                    api_key = str(adapter_config.get("api_key") or "").strip()
                    base_url = str(adapter_config.get("base_url") or "").strip().lower()
                    # Kimi Code 与 Moonshot 开放平台是两套认证通道。Kimi
                    # 适配器会按 Key 自动规范化地址；这里给出剩余的账号/权限提示。
                    if api_key.startswith("sk-kimi-") or "api.kimi.com/coding" in base_url:
                        raise AIProviderError(
                            "Kimi Code API Key 鉴权失败。系统已按 Kimi Code 使用 "
                            "https://api.kimi.com/coding/v1；请确认 Key 未过期、会员额度可用，"
                            "并将模型填写为 k3（界面中的 kimi-k3 会自动转换）。"
                        ) from exc
                    raise AIProviderError(
                        "Kimi API Key 无效或已过期，请确认使用 Moonshot API Platform 的 Key，"
                        "并核对接口地址（中国区通常为 https://api.moonshot.cn/v1，国际区为 https://api.moonshot.ai/v1）。"
                    ) from exc
                raise AIProviderError("火山方舟 API Key 无效或已过期，请在 AI 配置中重新保存 API Key。") from exc
            if "403" in error_text or "Forbidden" in error_text:
                provider_name = str(getattr(adapter, "provider", "")).lower()
                if provider_name == "kimi":
                    raise AIProviderError(
                        "Kimi API Key 没有访问当前模型的权限，请确认 Kimi Code 会员等级支持 k3，"
                        "或使用 Moonshot 开放平台中已开通的模型。"
                    ) from exc
                raise AIProviderError("当前 API Key 没有访问该模型的权限，请确认已开通 Doubao-Seed-Vision。") from exc
            if "image" in error_text.lower() or "vision" in error_text.lower() or "multimodal" in error_text.lower():
                provider_name = str(getattr(adapter, "provider", "")).lower()
                if provider_name == "kimi":
                    raise AIProviderError(
                        "当前 Kimi 接口拒绝首尾帧图片输入，请确认使用支持 image_in 的 Kimi K3，"
                        "并检查 Kimi Code 接口地址是否为 https://api.kimi.com/coding/v1。"
                    ) from exc
            if "InvalidEndpointOrModel.NotFound" in error_text or "Error code: 404" in error_text:
                provider_name = str(getattr(adapter, "provider", "")).lower()
                if provider_name == "kimi":
                    model = str((getattr(adapter, "config", {}) or {}).get("model") or "当前模型")
                    raise AIProviderError(
                        f"Kimi 接口找不到模型「{model}」。Kimi Code 的 K3 API 模型 ID 为 k3，"
                        "请检查模型字段和会员等级后重新保存。"
                    ) from exc
                model = str((getattr(adapter, "config", {}) or {}).get("model") or "当前模型")
                raise AIProviderError(
                    f"火山方舟找不到模型或推理接入点「{model}」。请在方舟控制台创建/启动视觉模型推理接入点，"
                    "再把 ep-... ID 填入系统设置的‘提示词大师’模型字段。"
                ) from exc
            provider_name = str(getattr(adapter, "provider", "")).lower()
            if provider_name == "kimi":
                raise AIProviderError(
                    "提示词大师调用 Kimi 失败，请检查 Kimi API Key、接口地址和模型 ID。"
                ) from exc
            raise AIProviderError(
                "提示词大师调用失败，请检查火山方舟模型 ID、API Key 和接口地址。"
            ) from exc
    raw_prompt = (prompt or "").strip()
    prompt = _limit_prompt(raw_prompt)
    structured: dict[str, Any] = {}
    generated_name = ""
    generated_description = ""
    # 视觉模型和文本模型都可能按要求返回 JSON；不能只在视觉模型分支解析，
    # 否则文本模型的整段 JSON 会直接落进“可编辑提示词”输入框。
    try:
        clean = re.sub(r"^```(?:json)?|```$", "", raw_prompt, flags=re.I | re.M).strip()
        # 兼容模型在 JSON 前追加“下面是结果：”或在末尾补充说明的情况。
        # 只截取最外层对象，避免整段 JSON 落入前端镜头提示词框。
        object_start = clean.find("{")
        object_end = clean.rfind("}")
        if object_start >= 0 and object_end > object_start:
            clean = clean[object_start:object_end + 1]
        parsed, _ = json.JSONDecoder().raw_decode(clean)
        if isinstance(parsed, dict):
            structured = parsed
            generated_name = str(structured.get("name") or structured.get("template_name") or "").strip()
            generated_description = str(structured.get("description") or "").strip()
            prompt = _limit_prompt(str(structured.get("prompt") or ""))
            negative = str(structured.get("negative_prompt") or negative).strip()
    except (ValueError, TypeError, json.JSONDecodeError):
        prompt = prompt.strip('"').strip()
    if require_real_ai:
        required_recipe_keys = {
            "camera", "timeline", "preserve", "allow_change", "negative", "recommended",
        }
        returned_recipe = dict(structured.get("recipe") or {}) if isinstance(structured, dict) and isinstance(structured.get("recipe"), dict) else {}
        # 兼容模型把 recipe 字段展开到 JSON 顶层的返回格式；这些内容仍然来自 AI，
        # 这里只做结构归并，不补造任何默认值。
        if isinstance(structured, dict):
            for key in required_recipe_keys:
                if not returned_recipe.get(key) and structured.get(key):
                    returned_recipe[key] = structured[key]
            if not returned_recipe.get("negative"):
                returned_recipe["negative"] = returned_recipe.get("negative_prompt") or structured.get("negative_prompt")
            if not returned_recipe.get("recommended") and (
                returned_recipe.get("recommended_duration") or structured.get("recommended_duration")
            ):
                returned_recipe["recommended"] = {
                    "duration": returned_recipe.get("recommended_duration") or structured.get("recommended_duration")
                }
            structured["recipe"] = returned_recipe
        missing_top_level = [
            key for key in ("name", "description", "prompt")
            if not str(structured.get(key) or "").strip()
        ] if isinstance(structured, dict) else ["name", "description", "prompt"]
        missing_recipe = (
            sorted(key for key in required_recipe_keys if not returned_recipe.get(key))
            if isinstance(returned_recipe, dict) else sorted(required_recipe_keys)
        )
        if missing_top_level or missing_recipe:
            missing = "、".join(missing_top_level + [f"recipe.{key}" for key in missing_recipe])
            raise AIProviderError(
                f"AI 未返回完整的模板配方（缺少：{missing}），系统不会使用默认配方，请重试。"
            )
    if not prompt:
        if not isinstance(adapter, MockMixin):
            raise AIProviderError("视觉模型未返回有效的提示词，请重试或检查模型配置。")
        prompt = _limit_prompt(_mock_prompt_master(
            generation_mode=generation_mode,
            intent=intent,
            template_default=template_default,
        ))
        generated_name = "建筑外景稳定运镜模板" if generation_mode == "first_last_frame_video" else "建筑外景展示模板"
        generated_description = (
            "适用于建筑外景的首尾帧连续镜头，保持建筑主体结构稳定，适合展示体量、立面与场地关系。"
            if generation_mode == "first_last_frame_video"
            else "适用于建筑外景展示，通过平稳推进镜头突出建筑主体、立面细节与整体空间关系。"
        )
        is_mock = True
    else:
        is_mock = False
    # 提示词大师的输出也经过一次规格清理，避免模板制作器等非快速生成
    # 页面绕过前端时，把“4K/超高清”带入可复用提示词。
    prompt = sanitize_prompt_resolution(prompt, resolution="720p")
    if not generated_name:
        generated_name = "建筑外景稳定运镜模板" if generation_mode == "first_last_frame_video" else "建筑外景展示模板"
    if not generated_description:
        generated_description = (
            f"适用于{intent.strip()}，根据参考帧生成平稳、连续的建筑展示镜头。"
            if intent and intent.strip()
            else "适用于建筑外景连续镜头，保持主体结构稳定并自然呈现空间、材质与光影变化。"
        )
    raw_warnings = structured.get("warnings")
    if isinstance(raw_warnings, str):
        warnings = [raw_warnings.strip()] if raw_warnings.strip() else []
    elif isinstance(raw_warnings, list):
        warnings = [str(item).strip() for item in raw_warnings if str(item).strip()]
    else:
        warnings = []
    recipe = _normalize_prompt_recipe(
        structured.get("recipe"),
        structured=structured,
        prompt=prompt,
        negative_prompt=negative,
        generation_mode=generation_mode,
        intent=intent,
    )
    return {
        "prompt": prompt,
        "name": generated_name[:128],
        "description": generated_description[:2000],
        "negative_prompt": negative,
        "mode": getattr(adapter, "provider", "llm"),
        "is_mock": is_mock,
        "provider": getattr(adapter, "provider", "llm"),
        "model": (getattr(adapter, "config", {}) or {}).get("model"),
        "vision_used": vision_used and not is_mock,
        "warnings": warnings,
        "recommended_duration": structured.get("recommended_duration"),
        "recipe": recipe,
    }
