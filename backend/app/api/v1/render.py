"""渲染 API 路由：源图上传、任务创建/查询、版本管理、遮罩、对比。"""

from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.factory import get_image_adapter, image_provider_info
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.project import Project
from app.models.render_job import RenderJob
from app.models.render_preset import RenderPreset
from app.models.render_version import RenderVersion
from app.models.user import User
from app.schemas.render import (
    CompareRequest,
    InpaintRequest,
    MaskUploadOut,
    OutpaintRequest,
    RenderTaskCreate,
    RenderTaskOut,
    RenderVersionOut,
    SourceImageMeta,
    SourceImageOut,
    UpscaleRequest,
)
from app.services.image_utils import (
    ImageValidationError,
    make_thumbnail,
    safe_filename,
    validate_and_process_image,
)
from app.services.prompt_builder import PromptBuildInput, build_prompts
from app.services.render_service import (
    create_render_job,
    ensure_v0_version,
    estimate_cost,
    run_render_job,
    soft_delete_version,
)
from app.tasks.render import render_job_task

router = APIRouter(prefix="/projects/{project_id}/render", tags=["画面渲染"])

logger = get_logger(__name__)

# 来源软件与镜头角度枚举
SOURCE_SOFTWARES = [
    "Revit", "Navisworks", "SketchUp", "3ds Max", "D5 Render",
    "Twinmotion", "SYNCHRO", "Bentley", "CAD", "其他",
]
CAMERA_ANGLES = [
    "总平面鸟瞰", "低空鸟瞰", "建筑人视", "正立面", "侧立面",
    "室内空间", "机电空间", "施工节点", "BIM剖切", "其他",
]


def _get_owned_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def _get_owned_asset(db: Session, project_id: str, asset_id: str, user: User) -> Asset:
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        raise NotFoundError("素材不存在或不属于当前项目")
    return asset


def _to_task_out(job: RenderJob) -> RenderTaskOut:
    return RenderTaskOut(
        id=job.id,
        project_id=job.project_id,
        source_asset_id=job.source_asset_id,
        preset_id=job.preset_id,
        operation_type=job.operation_type,
        positive_prompt=job.positive_prompt,
        negative_prompt=job.negative_prompt,
        aspect_ratio=job.aspect_ratio,
        output_width=job.output_width,
        output_height=job.output_height,
        variant_count=job.variant_count,
        structure_strength=job.structure_strength,
        creativity=job.creativity,
        seed=job.seed,
        provider=job.provider,
        model_name=job.model_name,
        status=job.status,
        progress=job.progress,
        error_message=job.error_message,
        estimated_cost=job.estimated_cost,
        actual_cost=job.actual_cost,
        currency=job.currency,
        is_conceptual=job.is_conceptual,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at.isoformat() if job.created_at else None,
        version_count=len(job.versions),
    )


# ============================================================
# 源图上传
# ============================================================

@router.post("/source-images", response_model=SourceImageOut, status_code=201, summary="上传模型截图")
async def upload_source_image(
    project_id: str,
    file: UploadFile = File(...),
    name: str = Form(...),
    source_software: str = Form("Revit"),
    project_stage: str | None = Form(None),
    camera_angle: str = Form("建筑人视"),
    is_original_model_shot: bool = Form(True),
    license_note: str | None = Form(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceImageOut:
    _get_owned_project(db, project_id, current)

    content = await file.read()
    fname = safe_filename(file.filename or "模型截图")
    try:
        info = validate_and_process_image(content, fname)
    except ImageValidationError as exc:
        raise ConflictError(str(exc))

    # SHA-256 去重
    dup = (
        db.query(Asset)
        .filter(
            Asset.project_id == project_id,
            Asset.sha256 == info["sha256"],
            Asset.is_original_model_shot.is_(True),
        )
        .first()
    )
    is_dup = dup is not None

    key = f"projects/{project_id}/model_shots/{uuid.uuid4().hex}.png"
    storage.save(key, info["processed_data"])

    # 缩略图
    from PIL import Image as PILImage

    img = PILImage.open(__import__("io").BytesIO(info["processed_data"]))
    thumb_data = make_thumbnail(img)
    thumb_key = key.replace(".png", "_thumb.png")
    storage.save(thumb_key, thumb_data)

    asset = Asset(
        project_id=project_id,
        name=name or fname,
        asset_type="image",
        source="model_shot",
        file_key=key,
        thumbnail_key=thumb_key,
        file_size=len(info["processed_data"]),
        mime_type=info["mime_type"],
        width=info["width"],
        height=info["height"],
        aspect_ratio=info["aspect_ratio"],
        color_mode=info["color_mode"],
        sha256=info["sha256"],
        is_original_model_shot=is_original_model_shot,
        source_software=source_software,
        project_stage=project_stage,
        camera_angle=camera_angle,
        license_note=license_note,
        is_ai_generated=False,
        meta={"source_filename": fname},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    # 建立 V0 版本
    ensure_v0_version(db, asset.id)

    return SourceImageOut(
        id=asset.id,
        project_id=asset.project_id,
        name=asset.name,
        asset_type=asset.asset_type,
        source=asset.source,
        file_key=asset.file_key,
        thumbnail_key=asset.thumbnail_key,
        url=f"/files/{asset.file_key}" if asset.file_key else None,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        aspect_ratio=asset.aspect_ratio,
        color_mode=asset.color_mode,
        sha256=asset.sha256,
        source_software=asset.source_software,
        camera_angle=asset.camera_angle,
        is_original_model_shot=asset.is_original_model_shot,
        is_duplicate=is_dup,
        duplicate_asset_id=dup.id if is_dup else None,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


@router.get("/source-images", response_model=list[SourceImageOut], summary="源图列表")
def list_source_images(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    assets = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.source.in_(["model_shot", "render"]))
        .order_by(Asset.created_at.desc())
        .all()
    )
    return [
        SourceImageOut(
            id=a.id,
            project_id=a.project_id,
            name=a.name,
            asset_type=a.asset_type,
            source=a.source,
            file_key=a.file_key,
            thumbnail_key=a.thumbnail_key,
            url=f"/files/{a.file_key}" if a.file_key else a.url,
            file_size=a.file_size,
            width=a.width,
            height=a.height,
            aspect_ratio=a.aspect_ratio,
            color_mode=a.color_mode,
            sha256=a.sha256,
            source_software=a.source_software,
            camera_angle=a.camera_angle,
            is_original_model_shot=a.is_original_model_shot,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in assets
    ]


@router.get("/enums", response_model=dict, summary="来源软件/镜头角度枚举")
def render_enums() -> dict:
    return {"source_softwares": SOURCE_SOFTWARES, "camera_angles": CAMERA_ANGLES}


# ============================================================
# Provider
# ============================================================

@router.get("/providers", response_model=list, summary="图片渲染 Provider 列表")
def list_providers() -> list:
    return image_provider_info()


@router.get("/providers/{provider}/capabilities", response_model=dict, summary="Provider 能力")
def provider_capabilities(provider: str) -> dict:
    adapter = get_image_adapter()
    if provider == "mock" or provider == adapter.provider:
        return adapter.capabilities()
    return {cap: False for cap in _ALL_CAP_KEYS}


_ALL_CAP_KEYS = [
    "text_to_image", "image_to_image", "inpaint", "outpaint", "upscale",
    "seed", "multiple_variants", "reference_image", "mask_image",
]


# ============================================================
# 渲染任务
# ============================================================

@router.post("/tasks", response_model=RenderTaskOut, status_code=202, summary="创建渲染任务")
def create_render_task(
    project_id: str,
    payload: RenderTaskCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderJob:
    _get_owned_project(db, project_id, current)

    # 幂等键检查
    if payload.idempotency_key:
        existing = (
            db.query(RenderJob)
            .filter(
                RenderJob.project_id == project_id,
                RenderJob.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if existing:
            return existing

    # 工程结构渲染只能以原始 BIM/模型截图为源，禁止将上一轮 AI 结果递归作为
    # 新源图；递归会快速放大建筑体量、构件与昼夜效果的偏差。
    source_asset = _get_owned_asset(db, project_id, payload.source_asset_id, current)
    if source_asset.source != "model_shot" and not payload.is_conceptual:
        raise ConflictError(
            "结构保持渲染只能选择“原始模型截图”。AI 生成的渲染图仅可作为概念创意图参考，"
            "不得递归作为工程 BIM 渲染源图。"
        )

    # 遮罩归属
    if payload.mask_asset_id:
        _get_owned_asset(db, project_id, payload.mask_asset_id, current)

    # 读取真实预设内容。此前错误地把用户输入重复作为 preset_prompt，导致
    # “建成效果夜景”等预设名称被记录、但夜景灯光指令从未发送给 Provider。
    preset_prompt = ""
    preset_negative = ""
    if payload.preset_id:
        preset = db.get(RenderPreset, payload.preset_id)
        if not preset or not preset.is_enabled:
            raise NotFoundError("渲染预设不存在或已停用")
        preset_prompt = preset.default_positive_prompt or ""
        preset_negative = preset.default_negative_prompt or ""

    # PromptBuilder 构建提示词
    build_input = PromptBuildInput(
        shot_description="",
        user_requirements=payload.positive_prompt,
        preset_prompt=preset_prompt,
        structure_strength=payload.structure_strength,
        preserve_logo=payload.preserve_logo,
        preserve_text=payload.preserve_text,
        preserve_roads=payload.preserve_roads,
        preserve_building_shape=payload.preserve_building_shape,
        preserve_equipment=payload.preserve_equipment,
        custom_constraints=payload.custom_constraints,
    )
    result = build_prompts(build_input)

    # 冲突拦截（默认阻止提交）
    if result.blocked and not payload.is_conceptual:
        raise ConflictError(
            "检测到可能改变工程结构的请求：" + "、".join(result.conflicts) +
            "。系统不得擅自修改建筑主体/层数/轮廓/道路等。如需继续，请联系管理员标记为「概念创意图」。"
        )

    positive = result.positive_prompt
    negative_parts = [payload.negative_prompt, preset_negative, result.negative_prompt]
    negative = "，".join(dict.fromkeys(part.strip() for part in negative_parts if part and part.strip()))

    # Provider 来源必须由实际 Adapter 决定。否则真实 MiniMax 结果会因前端默认值
    # "mock" 被错误标记，进而在正式导出预检中被拒绝。
    active_adapter = get_image_adapter()
    effective_provider = active_adapter.provider

    # 预估成本
    try:
        job = create_render_job(
            db=db,
            project_id=project_id,
            source_asset_id=payload.source_asset_id,
            preset_id=payload.preset_id,
            operation_type=payload.operation_type,
            positive_prompt=positive,
            negative_prompt=negative,
            aspect_ratio=payload.aspect_ratio,
            output_width=payload.output_width,
            output_height=payload.output_height,
            variant_count=payload.variant_count,
            structure_strength=payload.structure_strength,
            creativity=payload.creativity,
            seed=payload.seed,
            provider=effective_provider,
            model_name=payload.model_name or settings.ai_image_model,
            preserve_logo=payload.preserve_logo,
            preserve_text=payload.preserve_text,
            preserve_roads=payload.preserve_roads,
            preserve_building_shape=payload.preserve_building_shape,
            preserve_equipment=payload.preserve_equipment,
            custom_constraints=payload.custom_constraints,
            mask_asset_id=payload.mask_asset_id,
            idempotency_key=payload.idempotency_key,
            is_conceptual=payload.is_conceptual,
            concept_note=payload.concept_note,
            estimated_cost=0.0,
        )
    except IntegrityError:
        db.rollback()
        if not payload.idempotency_key:
            raise
        existing = (
            db.query(RenderJob)
            .filter(
                RenderJob.project_id == project_id,
                RenderJob.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if not existing:
            raise
        return _to_task_out(existing)
    job.estimated_cost = estimate_cost(job)
    db.commit()

    _dispatch_render(db, job)
    db.refresh(job)
    return _to_task_out(job)


def _dispatch_render(db: Session, job: RenderJob) -> None:
    """渲染任务分发：USE_CELERY 时异步，否则同步。RenderJob 自身跟踪状态。"""
    from app.core.config import settings

    if settings.use_celery:
        try:
            async_result = render_job_task.delay(job.id)
            job.celery_task_id = async_result.id
            db.commit()
        except Exception as exc:
            logger.warning("celery_render_fallback_sync", error=str(exc))
            try:
                run_render_job(job.id)
            except Exception:
                pass
    else:
        try:
            run_render_job(job.id)
        except Exception:
            # 状态已在 run_render_job 中标记为 failed
            pass


def _fake_render_task(db: Session, job: RenderJob):
    """保留兼容函数（不再使用 dispatch）。"""
    return None


@router.get("/tasks", response_model=list[RenderTaskOut], summary="渲染任务列表")
def list_render_tasks(
    project_id: str,
    status: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[RenderTaskOut]:
    _get_owned_project(db, project_id, current)
    query = db.query(RenderJob).filter(RenderJob.project_id == project_id)
    if status:
        query = query.filter(RenderJob.status == status)
    jobs = query.order_by(RenderJob.created_at.desc()).limit(100).all()
    return [_to_task_out(j) for j in jobs]


@router.get("/tasks/{task_id}", response_model=RenderTaskOut, summary="渲染任务详情（轮询）")
def get_render_task(
    project_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderTaskOut:
    _get_owned_project(db, project_id, current)
    job = db.get(RenderJob, task_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("渲染任务不存在")
    return _to_task_out(job)


@router.post("/tasks/{task_id}/retry", response_model=RenderTaskOut, summary="重试渲染任务")
def retry_render_task(
    project_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderTaskOut:
    _get_owned_project(db, project_id, current)
    job = db.get(RenderJob, task_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("渲染任务不存在")
    if job.status in ("success", "running"):
        raise ConflictError("仅失败任务可重试")
    job.status = "queued"
    job.error_message = None
    job.progress = 0
    db.commit()
    _dispatch_render(db, job)
    db.refresh(job)
    return _to_task_out(job)


@router.post("/tasks/{task_id}/cancel", response_model=RenderTaskOut, summary="取消渲染任务")
def cancel_render_task(
    project_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderTaskOut:
    _get_owned_project(db, project_id, current)
    job = db.get(RenderJob, task_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("渲染任务不存在")
    if job.status in ("queued", "running"):
        job.status = "cancelled"
        job.error_message = None
        db.commit()
    db.refresh(job)
    return _to_task_out(job)


@router.get("/tasks/{task_id}/results", response_model=list[RenderVersionOut], summary="任务结果版本")
def render_task_results(
    project_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[RenderVersion]:
    _get_owned_project(db, project_id, current)
    job = db.get(RenderJob, task_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("渲染任务不存在")
    return (
        db.query(RenderVersion)
        .filter(
            RenderVersion.render_job_id == task_id,
            RenderVersion.is_deleted.is_(False),
        )
        .order_by(RenderVersion.version_number.asc())
        .all()
    )


# ============================================================
# 版本管理
# ============================================================

@router.get("/versions", response_model=list[RenderVersionOut], summary="项目渲染版本列表")
def list_versions(
    project_id: str,
    source_asset_id: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[RenderVersion]:
    _get_owned_project(db, project_id, current)
    query = db.query(RenderVersion).filter(RenderVersion.is_deleted.is_(False))
    if source_asset_id:
        query = query.filter(RenderVersion.source_asset_id == source_asset_id)
    return query.order_by(RenderVersion.created_at.desc()).limit(200).all()


@router.get("/versions/{version_id}", response_model=RenderVersionOut, summary="版本详情")
def get_version(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderVersion:
    _get_owned_project(db, project_id, current)
    v = db.get(RenderVersion, version_id)
    if not v or v.is_deleted:
        raise NotFoundError("版本不存在")
    return v



@router.delete("/versions/{version_id}", status_code=204, summary="删除版本（软删除）")
def delete_version(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    try:
        soft_delete_version(db, project_id, version_id, current.username)
    except RuntimeError as exc:
        raise ConflictError(str(exc))


@router.post("/compare", response_model=dict, summary="对比任意两个版本")
def compare_versions(
    project_id: str,
    payload: CompareRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_owned_project(db, project_id, current)
    src = db.get(Asset, payload.source_asset_id)
    if not src or src.project_id != project_id:
        raise NotFoundError("源图不存在")
    source_bytes = storage.load(src.file_key) if src.file_key else b""

    versions = []
    for vid in payload.version_ids[:2]:
        v = db.get(RenderVersion, vid)
        if not v or v.is_deleted:
            continue
        asset = db.get(Asset, v.result_asset_id) if v.result_asset_id else None
        versions.append(
            {
                "version_id": v.id,
                "version_number": v.version_number,
                "asset_id": v.result_asset_id,
                "url": f"/files/{asset.file_key}" if asset and asset.file_key else None,
                "quality_status": v.quality_status,
                "quality_metrics": v.quality_metrics,
                "seed": v.seed,
            }
        )
    return {"source_url": f"/files/{src.file_key}" if src.file_key else None, "versions": versions}


# ============================================================
# 快捷操作：局部重绘 / 扩图 / 清晰度增强 / 遮罩
# ============================================================

@router.post("/mask", response_model=MaskUploadOut, status_code=201, summary="上传遮罩")
async def upload_mask(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> MaskUploadOut:
    _get_owned_project(db, project_id, current)
    content = await file.read()
    try:
        from PIL import Image as PILImage

        import io

        img = PILImage.open(io.BytesIO(content))
        img.load()
        if img.mode != "L":
            img = img.convert("L")
        width, height = img.size
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        processed = buf.getvalue()
    except Exception:
        raise ConflictError("遮罩必须为有效的 PNG 图片")

    key = f"projects/{project_id}/masks/{uuid.uuid4().hex}.png"
    storage.save(key, processed)
    mask_asset = Asset(
        project_id=project_id,
        name=f"遮罩-{uuid.uuid4().hex[:8]}",
        asset_type="image",
        source="render",
        file_key=key,
        file_size=len(processed),
        mime_type="image/png",
        width=width,
        height=height,
        is_ai_generated=False,
        meta={"is_mask": True},
    )
    db.add(mask_asset)
    db.commit()
    db.refresh(mask_asset)
    return MaskUploadOut(asset_id=mask_asset.id, width=width, height=height, file_key=key)


@router.post("/inpaint", response_model=RenderTaskOut, status_code=202, summary="局部重绘")
def inpaint(
    project_id: str,
    payload: Annotated[InpaintRequest, Body()],
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderJob:
    _get_owned_project(db, project_id, current)
    _get_owned_asset(db, project_id, payload.source_asset_id, current)
    mask = db.get(Asset, payload.mask_asset_id)
    if not mask or mask.project_id != project_id:
        raise NotFoundError("遮罩不存在")
    source = db.get(Asset, payload.source_asset_id)
    if mask.width != source.width or mask.height != source.height:
        raise ConflictError("遮罩尺寸与原图不一致")

    # 遮罩为空检查
    if _is_mask_empty(db, mask):
        raise ConflictError("遮罩为空，禁止提交局部重绘")

    adapter = get_image_adapter()
    if not adapter.supports("inpaint"):
        raise ConflictError("当前 Provider 不支持局部重绘")

    return create_render_task(
        project_id, RenderTaskCreate(
            source_asset_id=payload.source_asset_id,
            operation_type="inpaint",
            positive_prompt=payload.positive_prompt,
            mask_asset_id=payload.mask_asset_id,
            variant_count=payload.variant_count,
            seed=payload.seed,
            idempotency_key=payload.idempotency_key,
            aspect_ratio="16:9",
        ),
        db, current,
    )


def _is_mask_empty(db: Session, mask: Asset) -> bool:
    """检查遮罩是否全黑（空）。"""
    import io

    from PIL import Image

    try:
        data = storage.load(mask.file_key)
        img = Image.open(io.BytesIO(data)).convert("L")
        hist = img.histogram()
        # 全黑：最暗值占比>99%
        dark = sum(hist[:5]) / sum(hist) if sum(hist) else 1
        return dark > 0.99
    except Exception:
        return True


@router.post("/outpaint", response_model=RenderTaskOut, status_code=202, summary="16:9 扩图")
def outpaint(
    project_id: str,
    payload: OutpaintRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderJob:
    _get_owned_project(db, project_id, current)
    _get_owned_asset(db, project_id, payload.source_asset_id, current)
    adapter = get_image_adapter()
    if not adapter.supports("outpaint"):
        raise ConflictError("当前 Provider 不支持扩图")

    ratio = payload.target_ratio
    width, height = _ratio_to_size(ratio, payload.output_width, payload.output_height)
    return create_render_task(
        project_id, RenderTaskCreate(
            source_asset_id=payload.source_asset_id,
            operation_type="outpaint",
            positive_prompt=payload.positive_prompt,
            aspect_ratio=ratio,
            output_width=width,
            output_height=height,
            variant_count=payload.variant_count,
            seed=payload.seed,
            idempotency_key=payload.idempotency_key,
        ),
        db, current,
    )


def _ratio_to_size(ratio: str, ow: int | None, oh: int | None) -> tuple[int, int]:
    if ow and oh:
        return ow, oh
    mapping = {"16:9": (1920, 1080), "4:3": (1440, 1080), "1:1": (1080, 1080), "9:16": (1080, 1920)}
    w, h = mapping.get(ratio, (1920, 1080))
    return ow or w, oh or h


@router.post("/upscale", response_model=RenderTaskOut, status_code=202, summary="清晰度增强")
def upscale(
    project_id: str,
    payload: UpscaleRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderJob:
    _get_owned_project(db, project_id, current)
    _get_owned_asset(db, project_id, payload.source_asset_id, current)
    adapter = get_image_adapter()
    if not adapter.supports("upscale"):
        raise ConflictError("当前 Provider 不支持清晰度增强")
    return create_render_task(
        project_id, RenderTaskCreate(
            source_asset_id=payload.source_asset_id,
            operation_type="upscale",
            positive_prompt="清晰度增强，保持原图内容",
            variant_count=1,
            idempotency_key=payload.idempotency_key,
            aspect_ratio="16:9",
        ),
        db, current,
    )


@router.get("/audit", response_model=list, summary="审计日志（最近操作）")
def render_audit(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    from app.models.render_job import RenderJob

    jobs = (
        db.query(RenderJob)
        .filter(RenderJob.project_id == project_id)
        .order_by(RenderJob.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "event": f"渲染任务 {j.operation_type}",
            "status": j.status,
            "provider": j.provider,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "cost": j.actual_cost,
        }
        for j in jobs
    ]
