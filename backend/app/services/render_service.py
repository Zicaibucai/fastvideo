"""渲染服务：任务编排、质量检查、版本管理。

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

from sqlalchemy import func
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
    from app.services.ai_configuration import refresh_runtime_config_from_db

    refresh_runtime_config_from_db()

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
        db.query(RenderJob).filter(RenderJob.id == job.id).with_for_update().one()
        existing_max_version = (
            db.query(func.max(RenderVersion.version_number))
            .filter(RenderVersion.render_job_id == job.id)
            .scalar()
            or 0
        )
        created_versions = []
        for i, data in enumerate(results):
            version_number = int(existing_max_version) + i + 1
            # 质量检查
            metrics = quality_check(source_bytes_for_check, data)
            quality_status = metrics["quality_status"]

            # 保存图片
            result_key = (
                f"projects/{job.project_id}/render/{job.id}/"
                f"version_{version_number}_{seed}.png"
            )
            storage.save(result_key, data)
            thumb = make_thumbnail(_img_from_bytes(data))
            thumb_key = result_key.replace(".png", "_thumb.png")
            storage.save(thumb_key, thumb)

            # 创建 Asset
            asset = Asset(
                project_id=job.project_id,
                name=f"渲染V{version_number} ({job.operation_type})",
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
                version_number=version_number,
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
# 版本管理（渲染结果只属于素材库）
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


def soft_delete_version(db: Session, project_id: str, version_id: str, user_name: str) -> None:
    """删除未使用版本（软删除 + 分镜引用检查）。"""
    version = db.get(RenderVersion, version_id)
    if not version:
        raise RuntimeError("渲染版本不存在")
    result_asset = db.get(Asset, version.result_asset_id) if version.result_asset_id else None
    source_asset = db.get(Asset, version.source_asset_id) if version.source_asset_id else None
    if (result_asset and result_asset.project_id != project_id) or (source_asset and source_asset.project_id != project_id):
        raise RuntimeError("渲染版本不存在")

    # 版本只能由同项目分镜引用；被当前分镜使用时保留，避免素材库出现悬空画面。
    referenced = db.query(StoryboardShot).filter(
        StoryboardShot.project_id == project_id,
        StoryboardShot.render_version_id == version_id,
        StoryboardShot.is_active.is_(True),
    ).first()
    if referenced:
        raise RuntimeError("被引用版本不能删除")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    version.is_deleted = True
    version.deleted_by = user_name
    version.deleted_at = now
    db.commit()
