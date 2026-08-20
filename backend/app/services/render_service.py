"""渲染服务：任务编排、质量检查、版本管理、分镜绑定、视频段标记。

核心原则：
- AI 渲染仅用于视觉增强，不做工程模型自动校核。
- 所有 AI 生成图片带免责声明。
- 结构一致性检测结果标注为"辅助检查"，不能替代人工审核。
- 原图永远作为 V0，生成结果从 V1 开始，不覆盖旧版本。
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.factory import get_image_adapter
from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.render_job import RenderJob
from app.models.render_version import RenderVersion
from app.models.storyboard_shot import StoryboardShot
from app.services.image_utils import (
    AI_DISCLAIMER,
    encode_png,
    make_thumbnail,
    quality_check,
)
from app.services.prompt_builder import build_prompts

logger = get_logger(__name__)

AI_RENDER_DISCLAIMER = AI_DISCLAIMER


def create_render_job(
    db: Session,
    *,
    project_id: str,
    storyboard_shot_id: str | None,
    source_asset_id: str | None,
    preset_id: str | None,
    operation_type: str,
    positive_prompt: str,
    negative_prompt: str,
    aspect_ratio: str,
    output_width: int | None,
    output_height: int | None,
    variant_count: int,
    structure_strength: int,
    creativity: float,
    seed: int | None,
    provider: str,
    model_name: str | None,
    preserve_logo: bool,
    preserve_text: bool,
    preserve_roads: bool,
    preserve_building_shape: bool,
    preserve_equipment: bool,
    custom_constraints: list[str] | None,
    mask_asset_id: str | None,
    idempotency_key: str | None,
    is_conceptual: bool,
    concept_note: str | None,
    estimated_cost: float,
) -> RenderJob:
    job = RenderJob(
        project_id=project_id,
        storyboard_shot_id=storyboard_shot_id,
        source_asset_id=source_asset_id,
        preset_id=preset_id,
        operation_type=operation_type,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        aspect_ratio=aspect_ratio,
        output_width=output_width,
        output_height=output_height,
        variant_count=min(variant_count, 4),
        structure_strength=structure_strength,
        creativity=creativity,
        seed=seed,
        provider=provider,
        model_name=model_name,
        preserve_logo=preserve_logo,
        preserve_text=preserve_text,
        preserve_roads=preserve_roads,
        preserve_building_shape=preserve_building_shape,
        preserve_equipment=preserve_equipment,
        custom_constraints=custom_constraints or [],
        mask_asset_id=mask_asset_id,
        status="queued",
        progress=0,
        idempotency_key=idempotency_key,
        estimated_cost=estimated_cost,
        actual_cost=0.0,
        is_conceptual=is_conceptual,
        concept_note=concept_note,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def estimate_cost(job: RenderJob) -> float:
    """估计渲染成本（Mock 为 0，真实 Provider 可在 adapter 中实现）。"""
    if job.provider == "mock":
        return 0.0
    # 简单估算：每张图 0.05 元
    return round(job.variant_count * 0.05, 3)


def run_render_job(job_id: str) -> dict[str, Any]:
    """执行渲染任务主体。

    1. 标记 running
    2. 调用适配器（render/inpaint/outpaint/upscale）
    3. 对每个结果做质量检查
    4. 保存结果图片 → Asset → RenderVersion
    5. 更新任务状态
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(RenderJob, job_id)
        if not job:
            raise RuntimeError("渲染任务不存在")
        if job.status == "cancelled":
            return {"status": "cancelled"}

        job.status = "running"
        job.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        job.progress = 10
        job.error_message = None
        db.commit()

        # 读取源图
        source_bytes = None
        if job.source_asset_id:
            src = db.get(Asset, job.source_asset_id)
            if src and src.file_key:
                source_bytes = storage.load(src.file_key)

        adapter = get_image_adapter()
        if not adapter.is_available():
            raise RuntimeError("图片生成服务不可用，请检查配置。")

        # 调用适配器
        results: list[bytes] = []
        seed = job.seed if job.seed is not None else int(time.time()) % 100000
        if job.operation_type == "inpaint":
            if not job.mask_asset_id:
                raise RuntimeError("局部重绘缺少遮罩")
            mask_asset = db.get(Asset, job.mask_asset_id)
            if not mask_asset or not mask_asset.file_key:
                raise RuntimeError("遮罩文件不存在")
            mask_bytes = storage.load(mask_asset.file_key)
            if not adapter.supports("inpaint"):
                raise RuntimeError("当前 Provider 不支持局部重绘")
            results = adapter.inpaint_image(
                source_bytes, mask_bytes, job.positive_prompt,
                n=job.variant_count, seed=seed,
            )
        elif job.operation_type == "outpaint":
            if not adapter.supports("outpaint"):
                raise RuntimeError("当前 Provider 不支持扩图")
            results = adapter.outpaint_image(
                source_bytes, job.positive_prompt,
                target_size=f"{job.output_width or 1920}x{job.output_height or 1080}",
                n=job.variant_count, seed=seed,
            )
        elif job.operation_type == "upscale":
            if not adapter.supports("upscale"):
                raise RuntimeError("当前 Provider 不支持清晰度增强")
            results = adapter.upscale_image(source_bytes, scale=2)
        elif job.operation_type == "color_grade":
            if not adapter.supports("image_to_image"):
                raise RuntimeError("当前 Provider 不支持色彩优化")
            results = adapter.render_image(
                source_bytes, job.positive_prompt,
                negative_prompt=job.negative_prompt,
                seed=seed, n=job.variant_count,
            )
        else:  # render
            if not adapter.supports("image_to_image"):
                raise RuntimeError("当前 Provider 不支持图生图，不能降级为文生图")
            results = adapter.render_image(
                source_bytes, job.positive_prompt,
                negative_prompt=job.negative_prompt,
                seed=seed, n=job.variant_count,
            )

        job.progress = 60
        db.commit()

        # 保存结果
        source_bytes_for_check = source_bytes or _placeholder_bytes()
        created_versions = []
        for i, data in enumerate(results):
            # 质量检查
            metrics = quality_check(source_bytes_for_check, data)
            quality_status = metrics["quality_status"]

            # 保存图片
            result_key = (
                f"projects/{job.project_id}/render/{job.id}/"
                f"version_{i + 1}_{seed}.png"
            )
            storage.save(result_key, data)
            thumb = make_thumbnail(_img_from_bytes(data))
            thumb_key = result_key.replace(".png", "_thumb.png")
            storage.save(thumb_key, thumb)

            # 创建 Asset
            asset = Asset(
                project_id=job.project_id,
                name=f"渲染V{i + 1} ({job.operation_type})",
                asset_type="image",
                source="render",
                file_key=result_key,
                thumbnail_key=thumb_key,
                file_size=len(data),
                mime_type="image/png",
                width=_img_from_bytes(data).width,
                height=_img_from_bytes(data).height,
                is_ai_generated=True,
                ai_disclaimer=AI_RENDER_DISCLAIMER,
                is_conceptual=job.is_conceptual,
                generated_by=job.provider,
                prompt=job.positive_prompt,
                meta={
                    "render_job_id": job.id,
                    "seed": seed,
                    "operation": job.operation_type,
                    "concept_note": job.concept_note if job.is_conceptual else None,
                },
            )
            db.add(asset)
            db.flush()

            # 创建版本
            version = RenderVersion(
                render_job_id=job.id,
                source_asset_id=job.source_asset_id,
                result_asset_id=asset.id,
                version_number=i + 1,
                provider=job.provider,
                model_name=job.model_name,
                seed=seed,
                generation_type=job.operation_type,
                prompt_snapshot={"prompt": job.positive_prompt},
                negative_prompt_snapshot={"prompt": job.negative_prompt},
                parameter_snapshot={
                    "structure_strength": job.structure_strength,
                    "creativity": job.creativity,
                    "aspect_ratio": job.aspect_ratio,
                    "output_width": job.output_width,
                    "output_height": job.output_height,
                },
                quality_metrics=metrics,
                quality_status=quality_status,
            )
            db.add(version)
            created_versions.append(version)

        db.flush()
        job.progress = 90
        db.commit()

        # 质量检查结果处理：
        # - failed 结果不得设为正式分镜画面
        # - warning 结果允许人工确认后使用
        # 全部为 failed 时任务标记为 success（生成完成）但返回 warnings
        job.status = "success"
        job.progress = 100
        job.completed_at = time.strftime("%Y-%m-%d %H:%M:%S")
        job.actual_cost = estimate_cost(job)
        db.commit()

        return {
            "status": "success",
            "version_count": len(created_versions),
            "versions": [
                {
                    "id": v.id,
                    "version_number": v.version_number,
                    "quality_status": v.quality_status,
                    "asset_id": v.result_asset_id,
                    "asset_key": db.get(Asset, v.result_asset_id).file_key if v.result_asset_id else None,
                }
                for v in created_versions
            ],
        }
    except Exception as exc:
        logger.exception("render_job_failed", job_id=job_id)
        job = db.get(RenderJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)[:2000]
            job.completed_at = time.strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
        raise
    finally:
        db.close()


def _img_from_bytes(data: bytes):
    import io

    from PIL import Image

    return Image.open(io.BytesIO(data))


def _placeholder_bytes() -> bytes:
    """无源图时的占位（结构检查用）。"""
    return encode_png(_img_from_bytes(b"") if False else _make_placeholder_img())


def _make_placeholder_img():
    from PIL import Image

    return Image.new("RGB", (1280, 720), (30, 58, 95))


# ============================================================
# 版本管理与分镜绑定
# ============================================================

def ensure_v0_version(db: Session, asset_id: str) -> None:
    """为源图确保 V0 版本存在。"""
    src = db.get(Asset, asset_id)
    if not src:
        return
    existing = (
        db.query(RenderVersion)
        .filter(
            RenderVersion.source_asset_id == asset_id,
            RenderVersion.version_number == 0,
        )
        .first()
    )
    if existing:
        return
    v0 = RenderVersion(
        render_job_id=None,
        source_asset_id=asset_id,
        result_asset_id=asset_id,
        version_number=0,
        provider="original",
        generation_type="original",
        quality_metrics={"quality_status": "passed", "note": "原始模型截图"},
        quality_status="passed",
    )
    db.add(v0)
    db.commit()


def select_version_for_shot(
    db: Session,
    project_id: str,
    shot_id: str,
    version_id: str,
    user_name: str,
) -> dict[str, Any]:
    """将某个渲染版本设为分镜当前画面。

    1. 更新分镜当前画面引用（image_asset_id + render_version_id + source_model_asset_id）
    2. 记录选择历史
    3. 若分镜已被视频工程使用，标记相关视频段需要重新生成
    4. 返回分镜更新结果
    """
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise RuntimeError("分镜不存在")

    version = db.get(RenderVersion, version_id)
    if not version:
        raise RuntimeError("渲染版本不存在")
    if version.quality_status == "failed":
        raise RuntimeError("结构一致性检查未通过（failed）的版本不能设为正式分镜画面")

    result_asset = db.get(Asset, version.result_asset_id) if version.result_asset_id else None
    if result_asset and result_asset.project_id != project_id:
        raise RuntimeError("素材不属于当前项目")

    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # 更新版本选择状态（取消旧选择）
    db.query(RenderVersion).filter(
        RenderVersion.render_job_id == version.render_job_id,
        RenderVersion.is_selected.is_(True),
    ).update({"is_selected": False})
    version.is_selected = True
    version.selected_by = user_name
    version.selected_at = now

    # 更新分镜
    old_image_id = shot.image_asset_id
    shot.image_asset_id = result_asset.id if result_asset else old_image_id
    shot.render_version_id = version.id
    if result_asset:
        shot.visual_review_status = "approved"
        # 记录来源链：分镜 → 结果素材 → 渲染版本 → 原始模型截图
        if version.source_asset_id:
            shot.source_model_asset_id = version.source_asset_id
        # 结果图自动加入素材库（已创建 Asset）

    # 记录选择历史
    history = list(shot.visual_history or [])
    history.append(
        {
            "version_id": version.id,
            "asset_id": result_asset.id if result_asset else None,
            "selected_by": user_name,
            "selected_at": now,
        }
    )
    shot.visual_history = history

    # 视频工程标记需重建
    affected_videos = _mark_video_segments_rebuild(db, project_id, shot_id)

    db.commit()
    db.refresh(shot)

    return {
        "shot_id": shot_id,
        "image_asset_id": shot.image_asset_id,
        "render_version_id": version.id,
        "visual_review_status": shot.visual_review_status,
        "affected_videos": affected_videos,
    }


def _mark_video_segments_rebuild(
    db: Session,
    project_id: str,
    shot_id: str,
    reason: str = "分镜画面已更换",
) -> list[str]:
    """若分镜被视频工程使用，标记相关视频分段需要重新生成。"""
    from app.models.video_project import VideoProject

    affected = []
    vps = (
        db.query(VideoProject)
        .filter(VideoProject.project_id == project_id)
        .all()
    )
    for vp in vps:
        timeline = vp.timeline or []
        changed = False
        for item in timeline:
            if isinstance(item, dict) and item.get("shot_id") == shot_id:
                item["needs_rebuild"] = True
                item["rebuild_reason"] = reason
                changed = True
            elif isinstance(item, list) and len(item) > 0 and item[0] == shot_id:
                # 兼容旧格式 [shot_id, sequence, duration]
                changed = True
        if changed:
            vp.timeline = timeline
            if vp.status == "success":
                vp.status = "draft"
            vp.meta = {
                **(vp.meta or {}),
                "rebuild_required": True,
                "rebuild_reason": reason,
            }
            affected.append(vp.id)
    if affected:
        db.commit()
    return affected


def restore_shot_visual(db: Session, project_id: str, shot_id: str, version_id: str, user_name: str) -> dict:
    """恢复历史选择（版本恢复只改变当前选择，不复制文件）。"""
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise RuntimeError("分镜不存在")
    history = shot.visual_history or []
    target = next((h for h in history if h.get("version_id") == version_id), None)
    if not target:
        raise RuntimeError("历史选择不存在")

    version = db.get(RenderVersion, version_id)
    if not version:
        raise RuntimeError("渲染版本不存在")

    result_asset = db.get(Asset, version.result_asset_id) if version.result_asset_id else None
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    shot.image_asset_id = result_asset.id if result_asset else shot.image_asset_id
    shot.render_version_id = version.id
    shot.visual_review_status = "approved"
    if version.source_asset_id:
        shot.source_model_asset_id = version.source_asset_id

    history.append(
        {
            "version_id": version.id,
            "asset_id": result_asset.id if result_asset else None,
            "selected_by": user_name,
            "selected_at": now,
            "restored": True,
        }
    )
    shot.visual_history = history
    db.commit()
    db.refresh(shot)
    return {"shot_id": shot_id, "render_version_id": version.id}


def soft_delete_version(db: Session, project_id: str, version_id: str, user_name: str) -> None:
    """删除未使用版本（软删除 + 引用检查）。"""
    version = db.get(RenderVersion, version_id)
    if not version:
        raise RuntimeError("渲染版本不存在")

    # 引用检查：是否被分镜引用
    referenced = (
        db.query(StoryboardShot)
        .filter(
            StoryboardShot.project_id == project_id,
            StoryboardShot.render_version_id == version_id,
        )
        .first()
    )
    if referenced:
        raise RuntimeError("该版本正被分镜引用，不能删除")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    version.is_deleted = True
    version.deleted_by = user_name
    version.deleted_at = now
    db.commit()
