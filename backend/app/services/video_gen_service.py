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
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.base import MockMixin
from app.adapters.factory import build_video_adapter, get_llm_adapter, get_video_adapter
from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.storyboard_shot import StoryboardShot
from app.models.video_generation import (
    VideoGenerationJob,
    VideoGenerationTemplate,
    VideoGenerationVersion,
)
from app.services.video_gen_templates import ARCH_CONSTRAINTS, ARCH_NEGATIVE, SYSTEM_TEMPLATES

logger = get_logger(__name__)

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


def check_arch_conflicts(text: str) -> list[str]:
    """检测用户视频提示词中的结构修改冲突请求。"""
    if not text:
        return []
    conflicts = []
    for pattern, desc in CONFLICT_PATTERNS:
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
    constraints = list(arch_constraints or ARCH_CONSTRAINTS) if constraints_enabled else []

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

def create_video_job(
    db: Session,
    *,
    project_id: str,
    storyboard_shot_id: str | None,
    generation_mode: str,
    first_frame_asset_id: str,
    last_frame_asset_id: str | None,
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
) -> VideoGenerationJob:
    """创建视频生成任务（含完整参数快照与建筑约束快照）。"""
    # 冲突检测
    conflicts = check_arch_conflicts(positive_prompt or "")
    if conflicts:
        raise ValueError("检测到可能改变工程结构的请求：" + "、".join(conflicts) +
                         "。禁止增加楼层、改变建筑轮廓、移动道路或替换主楼等结构性修改。")

    # 读取模板默认约束（若模板存在）
    template_constraints: list[str] | None = None
    if template_id:
        template = db.get(VideoGenerationTemplate, template_id)
        if template and template.is_enabled:
            template_constraints = template.default_arch_constraints or ARCH_CONSTRAINTS

    arch_constraints = list(template_constraints or ARCH_CONSTRAINTS) if constraints_enabled else []

    final_positive, final_negative = build_final_prompt(
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        constraints_enabled=constraints_enabled,
        arch_constraints=arch_constraints,
    )

    # Provider 与模型：用户显式选择时按其构建（未配置 Key 直接报错，不静默降级）；
    # 未选择时用全局默认适配器。
    if provider:
        adapter = build_video_adapter(provider)
        if adapter is None or not adapter.is_available():
            raise ValueError(
                f"视频 Provider「{provider}」未配置 API Key 或不可用，请在 .env 配置后重试。"
            )
        provider = adapter.provider
    else:
        adapter = get_video_adapter()
        provider = adapter.provider

    model_defaults = {
        "seedance": settings.seedance_video_model,
        "minimax": settings.minimax_video_model,
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
        "template_id": template_id,
        "user_prompt": positive_prompt or "",
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "seed": seed,
        "generate_audio": generate_audio,
        "constraints_enabled": constraints_enabled,
        "architecture_constraints": arch_constraints,
        "provider": provider,
        "model_name": final_model,
    }

    job = VideoGenerationJob(
        project_id=project_id,
        storyboard_shot_id=storyboard_shot_id,
        generation_mode=generation_mode,
        first_frame_asset_id=first_frame_asset_id,
        last_frame_asset_id=last_frame_asset_id,
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

        if mode == "image_to_video" and not first_frame_bytes:
            raise RuntimeError("图生视频必须选择首帧图片，未检测到首帧。")
        if mode == "first_last_frame_video" and (not first_frame_bytes or not last_frame_bytes):
            raise RuntimeError("首尾帧模式必须同时选择首帧与尾帧两张图片，不允许降级为普通图生视频。")

        adapter = build_video_adapter(job.provider)
        if adapter is None or not adapter.is_available():
            raise RuntimeError(
                f"任务使用的视频 Provider「{job.provider}」当前不可用（未配置 API Key），无法执行。"
            )
        if mode == "image_to_video" and not adapter.supports("image_to_video"):
            raise RuntimeError(f"Provider「{job.provider}」不支持图生视频。")
        if mode == "first_last_frame_video" and not adapter.supports("first_last_frame_video"):
            raise RuntimeError(f"Provider「{job.provider}」不支持首尾帧视频，且不允许降级为普通图生视频。")

        job.progress = 20
        db.commit()

        prompt = job.positive_prompt or ""
        video_bytes: bytes | None = None
        provider_task_id: str | None = None

        if job.provider in ("seedance", "minimax"):
            # Seedance / MiniMax H3 三段式：创建任务 → 轮询 → 下载
            provider_task_id = adapter.create_generation_task(
                prompt=prompt,
                first_frame_bytes=first_frame_bytes,
                last_frame_bytes=last_frame_bytes,
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
                prompt,
                duration=float(job.duration),
                first_frame_bytes=first_frame_bytes,
                resolution=job.resolution,
                seed=job.seed,
            )

        if not video_bytes:
            raise RuntimeError("视频生成结果为空")

        job.progress = 90
        db.commit()

        # 保存结果 Asset
        result_key = f"projects/{job.project_id}/ai_video/{job.id}/result_{int(time.time())}.mp4"
        storage.save(result_key, video_bytes)
        duration_seconds = float(job.duration)

        asset = Asset(
            project_id=job.project_id,
            name=f"AI视频-{job.generation_mode}-{job.id[:8]}",
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
            meta={"is_mock": job.provider == "mock", "video_job_id": job.id},
        )
        db.add(asset)
        db.flush()

        # 版本号：同一任务内递增
        existing_versions = (
            db.query(VideoGenerationVersion)
            .filter(VideoGenerationVersion.video_job_id == job.id)
            .count()
        )
        version = VideoGenerationVersion(
            video_job_id=job.id,
            result_asset_id=asset.id,
            version_number=existing_versions + 1,
            provider=job.provider,
            model_name=job.model_name,
            seed=job.seed,
            generation_mode=job.generation_mode,
            prompt_snapshot={"prompt": job.positive_prompt},
            negative_prompt_snapshot={"prompt": job.negative_prompt},
            parameter_snapshot=job.parameter_snapshot,
            first_frame_asset_id=job.first_frame_asset_id,
            last_frame_asset_id=job.last_frame_asset_id,
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

    db.query(VideoGenerationVersion).filter(
        VideoGenerationVersion.video_job_id == job.id,
        VideoGenerationVersion.is_selected.is_(True),
    ).update({"is_selected": False})
    version.is_selected = True
    version.selected_by = user_name
    version.selected_at = time.strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    db.refresh(version)
    return version


def bind_version_to_shot(
    db: Session, project_id: str, version_id: str, shot_id: str, user_name: str
) -> dict[str, Any]:
    """把生成完成的视频手动绑定回某个分镜。"""
    version = db.get(VideoGenerationVersion, version_id)
    if not version or version.is_deleted:
        raise RuntimeError("视频版本不存在")
    job = db.get(VideoGenerationJob, version.video_job_id)
    if not job or job.project_id != project_id:
        raise RuntimeError("视频任务不存在或不属于当前项目")

    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise RuntimeError("分镜不存在或不属于当前项目")

    asset = db.get(Asset, version.result_asset_id) if version.result_asset_id else None
    if not asset:
        raise RuntimeError("视频结果素材不存在，无法绑定分镜")

    shot.video_asset_id = asset.id
    shot.video_clip_key = asset.file_key
    shot.video_prompt = None  # 不把生成提示词回写解说词页面
    shot.status = "ai_done" if shot.status in ("draft", "ai_generating") else shot.status

    version.bound_shot_id = shot.id
    version.selected_by = user_name
    version.selected_at = time.strftime("%Y-%m-%d %H:%M:%S")
    if not version.is_selected:
        version.is_selected = True
    db.commit()
    db.refresh(version)
    return {
        "version_id": version.id,
        "shot_id": shot.id,
        "video_asset_id": asset.id,
        "video_clip_key": asset.file_key,
        "shot_sequence": shot.sequence,
    }


def soft_delete_version(db: Session, project_id: str, version_id: str, user_name: str) -> None:
    """删除未使用的视频版本（软删除 + 绑定检查）。"""
    version = db.get(VideoGenerationVersion, version_id)
    if not version:
        raise RuntimeError("视频版本不存在")
    job = db.get(VideoGenerationJob, version.video_job_id)
    if not job or job.project_id != project_id:
        raise RuntimeError("视频任务不存在或不属于当前项目")
    if version.bound_shot_id:
        raise RuntimeError("该版本已绑定分镜，请先解除绑定再删除")
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


def generate_prompt_master(
    db: Session,
    project_id: str,
    *,
    first_frame_asset_id: str | None,
    last_frame_asset_id: str | None,
    reference_asset_ids: list[str] | None,
    template_id: str | None,
    intent: str | None,
    generation_mode: str,
) -> dict[str, Any]:
    """「提示词大师」：读取参考帧信息 + 用户意图，生成视频生成提示词。

    当前 LLM（deepseek）不支持视觉输入，因此以参考帧的名称/尺寸 + 模板默认提示词 +
    用户意图作为上下文交给 LLM 组织提示词；若接入视觉模型，可在 ``messages`` 中将
    ``content`` 扩展为 ``[{"type":"text",...},{"type":"image_url",...}]``。
    Mock / 未配置 Key 时返回确定性的默认提示词，保证演示可运行。
    """
    ids = [i for i in (first_frame_asset_id, last_frame_asset_id) if i] + list(reference_asset_ids or [])
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
        frame_lines.append(f"{idx}. {a.name or '未命名'}（{dim}）")
    frames_text = "\n".join(frame_lines)

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

    mode_label = "首尾帧视频（首帧→尾帧过渡）" if generation_mode == "first_last_frame_video" else "图生视频（单张参考图）"
    intent_text = (intent or "").strip() or "无（由 AI 按参考帧自主拟定镜头与氛围）"

    adapter = get_llm_adapter()
    if isinstance(adapter, MockMixin):
        return {
            "prompt": _mock_prompt_master(
                generation_mode=generation_mode,
                intent=intent,
                template_default=template_default,
            ),
            "negative_prompt": negative,
            "mode": "mock",
            "is_mock": True,
        }

    user_msg = (
        "你是一名建筑工程投标视频的「提示词大师」。请根据以下参考帧与用户意图，"
        "为 AI 视频生成写一段精炼的中文提示词。\n"
        "要求：\n"
        "1. 明确镜头运动（如缓慢推进 / 环绕 / 固定微动 / 俯冲）；\n"
        "2. 保持建筑主体数量、体量、轮廓、层数、道路、主入口与主要构件关系不变；\n"
        "3. 若为首尾帧模式，说明首帧到尾帧的画面过渡方式与最终成片质感；\n"
        "4. 只输出提示词正文（不超过 200 字），不要解释、不要编号、不要 Markdown。\n\n"
        f"生成模式：{mode_label}\n"
        f"参考帧：\n{frames_text}\n"
        f"用户意图：{intent_text}\n"
        f"可选模板默认提示词：{template_default or '无'}\n"
        f"必须保持的工程结构：{arch_hint}"
    )
    prompt = ""
    try:
        prompt = adapter.chat(
            [{"role": "user", "content": user_msg}],
            temperature=0.6,
            max_tokens=800,
        )
    except Exception:
        logger.exception("prompt_master_llm_error")
    prompt = (prompt or "").strip().strip('"').strip()
    if not prompt:
        prompt = _mock_prompt_master(
            generation_mode=generation_mode,
            intent=intent,
            template_default=template_default,
        )
        is_mock = True
    else:
        is_mock = False
    return {
        "prompt": prompt,
        "negative_prompt": negative,
        "mode": getattr(adapter, "provider", "llm"),
        "is_mock": is_mock,
    }
