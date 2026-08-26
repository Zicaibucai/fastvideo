"""纯函数形式的视频提示词编译工具。

将提示词解析、约束合并和时序换算与视频任务编排分离，便于单元测试。
"""

from __future__ import annotations

import re
from typing import Any

from app.services.construction_prompt import (
    construction_transition_is_controlled,
    normalize_construction_recipe,
    compile_construction_prompt,
)
from app.services.video_gen_templates import ARCH_CONSTRAINTS, ARCH_NEGATIVE

SEEDANCE_PROMPT_LIMIT = 2000

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
    if not value or not resolution or not _PROMPT_RESOLUTION_RE.search(value):
        return value
    value = _PROMPT_RESOLUTION_RE.sub("", value)
    value = re.sub(r"[（(]\s*[）)]", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    value = re.sub(r"([，,；;。])\s*([，,；;])+", r"\1", value)
    return value.strip(" ，,；;。")


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
