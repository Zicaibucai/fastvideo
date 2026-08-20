"""AI 视频生成 API（Phase 6/7：Seedance 图片驱动视频分镜）。

独立于「解说词与分镜」页面的视频生成模块：
- 模板列表 / 管理（10 个内置 + 企业自定义）
- 创建/查询/取消/重试视频生成任务
- 结果版本管理（预览/下载/选为当前结果/绑定分镜/删除）
- 建筑约束冲突预检
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.factory import (
    build_video_adapter,
    get_video_adapter,
    video_providers_info,
)
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.asset import Asset
from app.models.project import Project
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.models.video_generation import (
    VideoGenerationJob,
    VideoGenerationTemplate,
    VideoGenerationVersion,
)
from app.schemas.video_gen import (
    BindToShotRequest,
    ConstraintCheckRequest,
    ConstraintCheckResult,
    PromptMasterRequest,
    PromptMasterResult,
    ReferenceImageOut,
    VideoGenerationJobCreate,
    VideoGenerationJobOut,
    VideoGenerationTemplateCreate,
    VideoGenerationTemplateOut,
    VideoGenerationTemplateUpdate,
    VideoGenerationVersionOut,
)
from app.services.video_gen_service import (
    bind_version_to_shot,
    check_arch_conflicts,
    create_video_job,
    generate_prompt_master,
    run_video_job,
    seed_video_generation_templates,
    select_version,
    soft_delete_version,
)
from app.tasks.video_gen import video_gen_job_task

router = APIRouter(prefix="/projects/{project_id}/ai-video", tags=["AI 视频生成"])

logger = get_logger(__name__)


# ---------------- 辅助 ----------------

def _get_owned_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def _job_to_out(job: VideoGenerationJob) -> VideoGenerationJobOut:
    result_url = None
    if job.result_asset_id:
        asset = job.result_asset
        if asset and asset.file_key:
            result_url = f"/files/{asset.file_key}"
    return VideoGenerationJobOut(
        id=job.id,
        project_id=job.project_id,
        storyboard_shot_id=job.storyboard_shot_id,
        generation_mode=job.generation_mode,
        first_frame_asset_id=job.first_frame_asset_id,
        last_frame_asset_id=job.last_frame_asset_id,
        template_id=job.template_id,
        positive_prompt=job.positive_prompt,
        negative_prompt=job.negative_prompt,
        architecture_constraints=job.architecture_constraints,
        constraints_enabled=job.constraints_enabled,
        provider=job.provider,
        model_name=job.model_name,
        duration=job.duration,
        aspect_ratio=job.aspect_ratio,
        resolution=job.resolution,
        seed=job.seed,
        generate_audio=job.generate_audio,
        watermark=job.watermark,
        provider_task_id=job.provider_task_id,
        status=job.status,
        progress=job.progress,
        error_message=job.error_message,
        elapsed_seconds=job.elapsed_seconds,
        result_asset_id=job.result_asset_id,
        result_url=result_url,
        parameter_snapshot=job.parameter_snapshot,
        created_by=job.created_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at.isoformat() if job.created_at else None,
        version_count=len(job.versions),
    )


def _version_to_out(version: VideoGenerationVersion) -> VideoGenerationVersionOut:
    result_url = None
    if version.result_asset_id and version.result_asset and version.result_asset.file_key:
        result_url = f"/files/{version.result_asset.file_key}"
    bound_title = None
    if version.bound_shot_id and version.bound_shot:
        bound_title = (
            f"#{version.bound_shot.sequence} {version.bound_shot.title or ''}".strip()
        )
    return VideoGenerationVersionOut(
        id=version.id,
        video_job_id=version.video_job_id,
        result_asset_id=version.result_asset_id,
        result_url=result_url,
        version_number=version.version_number,
        provider=version.provider,
        model_name=version.model_name,
        seed=version.seed,
        generation_mode=version.generation_mode,
        prompt_snapshot=version.prompt_snapshot,
        negative_prompt_snapshot=version.negative_prompt_snapshot,
        parameter_snapshot=version.parameter_snapshot,
        first_frame_asset_id=version.first_frame_asset_id,
        last_frame_asset_id=version.last_frame_asset_id,
        template_id=version.template_id,
        is_selected=version.is_selected,
        selected_by=version.selected_by,
        selected_at=version.selected_at,
        bound_shot_id=version.bound_shot_id,
        bound_shot_title=bound_title,
        is_deleted=version.is_deleted,
        created_at=version.created_at.isoformat() if version.created_at else None,
    )


def _dispatch_video_job(db: Session, job: VideoGenerationJob) -> None:
    """分发：USE_CELERY 时异步，否则同步。任务状态由 run_video_job 跟踪。"""
    if settings.use_celery:
        try:
            async_result = video_gen_job_task.delay(job.id)
            job.celery_task_id = async_result.id
            db.commit()
        except Exception as exc:
            logger.warning("celery_video_gen_fallback_sync", error=str(exc))
            try:
                run_video_job(job.id)
            except Exception:
                pass
    else:
        try:
            run_video_job(job.id)
        except Exception:
            pass


def _template_out(t: VideoGenerationTemplate) -> VideoGenerationTemplateOut:
    return VideoGenerationTemplateOut(
        id=t.id,
        name=t.name,
        description=t.description,
        applicable_modes=t.applicable_modes,
        default_positive_prompt=t.default_positive_prompt,
        default_negative_prompt=t.default_negative_prompt,
        recommended_duration=t.recommended_duration,
        recommended_aspect_ratio=t.recommended_aspect_ratio,
        recommended_resolution=t.recommended_resolution,
        recommended_camera_motion=t.recommended_camera_motion,
        default_arch_constraints=t.default_arch_constraints,
        is_system=t.is_system,
        is_enabled=t.is_enabled,
        created_by=t.created_by,
        sort_order=t.sort_order,
        source_template_id=t.source_template_id,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


# ============================================================
# 模板
# ============================================================

@router.get("/templates", response_model=list[VideoGenerationTemplateOut], summary="视频模板列表")
def list_templates(
    project_id: str,
    mode: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    templates = (
        db.query(VideoGenerationTemplate)
        .filter(VideoGenerationTemplate.is_enabled.is_(True))
        .order_by(
            VideoGenerationTemplate.is_system.desc(),
            VideoGenerationTemplate.sort_order.asc(),
        )
        .all()
    )
    if mode:
        templates = [
            t for t in templates
            if t.applicable_modes and mode in (t.applicable_modes or [])
        ]
    return [_template_out(t) for t in templates]


@router.get("/templates/{template_id}", response_model=VideoGenerationTemplateOut, summary="模板详情")
def get_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    t = db.get(VideoGenerationTemplate, template_id)
    if not t or not t.is_enabled:
        raise NotFoundError("模板不存在")
    return _template_out(t)


@router.post("/templates", response_model=VideoGenerationTemplateOut, status_code=201, summary="创建企业模板")
def create_template(
    project_id: str,
    payload: VideoGenerationTemplateCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    t = VideoGenerationTemplate(
        name=payload.name,
        description=payload.description,
        applicable_modes=payload.applicable_modes or ["image_to_video"],
        default_positive_prompt=payload.default_positive_prompt,
        default_negative_prompt=payload.default_negative_prompt,
        recommended_duration=payload.recommended_duration,
        recommended_aspect_ratio=payload.recommended_aspect_ratio,
        recommended_resolution=payload.recommended_resolution,
        recommended_camera_motion=payload.recommended_camera_motion,
        default_arch_constraints=payload.default_arch_constraints,
        is_system=False,
        is_enabled=payload.is_enabled,
        created_by=current.username,
        sort_order=100,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _template_out(t)


@router.patch("/templates/{template_id}", response_model=VideoGenerationTemplateOut, summary="更新模板")
def update_template(
    project_id: str,
    template_id: str,
    payload: VideoGenerationTemplateUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    t = db.get(VideoGenerationTemplate, template_id)
    if not t:
        raise NotFoundError("模板不存在")
    if t.is_system and not current.is_superuser:
        raise ForbiddenError("系统模板仅管理员可修改")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return _template_out(t)


@router.delete("/templates/{template_id}", status_code=204, summary="删除模板")
def delete_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    t = db.get(VideoGenerationTemplate, template_id)
    if not t:
        raise NotFoundError("模板不存在")
    if t.is_system:
        raise ForbiddenError("系统模板不可删除，可停用")
    db.delete(t)
    db.commit()


# ============================================================
# Provider / 参考帧 / 约束预检
# ============================================================

@router.get("/providers", response_model=list, summary="视频 Provider 列表（含可用性与模型）")
def list_providers(project_id: str, current: User = Depends(get_current_user)):
    return video_providers_info()


@router.get("/providers/{provider}/capabilities", response_model=dict, summary="Provider 能力")
def provider_capabilities(
    project_id: str,
    provider: str,
    current: User = Depends(get_current_user),
):
    adapter = build_video_adapter(provider) or get_video_adapter()
    if provider == "mock" or provider == adapter.provider:
        return adapter.capabilities()
    return {cap: False for cap in _ALL_VIDEO_CAPS}


_ALL_VIDEO_CAPS = [
    "text_to_video", "image_to_video", "first_last_frame_video",
    "async_task", "cancel_task", "generate_audio",
]


@router.get("/reference-images", response_model=list[ReferenceImageOut], summary="可作首/尾帧的图片素材")
def list_reference_images(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回项目素材库中的图片素材（上传/模型截图/渲染图/AI 图），
    由用户主动选择作为首帧/尾帧，禁止系统自动挑选。"""
    _get_owned_project(db, project_id, current)
    assets = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.asset_type == "image")
        .order_by(Asset.created_at.desc())
        .all()
    )
    return [
        ReferenceImageOut(
            id=a.id,
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
            created_at=a.created_at,
        )
        for a in assets
    ]


@router.post("/constraint-check", response_model=ConstraintCheckResult, summary="建筑约束冲突预检")
def constraint_check(
    project_id: str,
    payload: ConstraintCheckRequest,
    current: User = Depends(get_current_user),
):
    conflicts = check_arch_conflicts(payload.text or "")
    return ConstraintCheckResult(conflicts=conflicts, blocked=bool(conflicts))


@router.post("/prompt-master", response_model=PromptMasterResult, summary="提示词大师：读参考帧生成视频提示词")
def prompt_master(
    project_id: str,
    payload: PromptMasterRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """读取参考帧（首帧/尾帧/多图）+ 可选用户意图，调用 LLM 生成视频提示词。

    LLM 未配置 Key 或不可用时自动返回确定性演示提示词，保证流程可运行。
    """
    _get_owned_project(db, project_id, current)
    ids = [i for i in (payload.first_frame_asset_id, payload.last_frame_asset_id) if i]
    ids += payload.reference_asset_ids or []
    if not [i for i in ids if i]:
        raise HTTPException(status_code=400, detail="请先选择至少一张参考帧图片")
    result = generate_prompt_master(
        db,
        project_id,
        first_frame_asset_id=payload.first_frame_asset_id,
        last_frame_asset_id=payload.last_frame_asset_id,
        reference_asset_ids=payload.reference_asset_ids,
        template_id=payload.template_id,
        intent=payload.intent,
        generation_mode=payload.generation_mode,
    )
    return PromptMasterResult(**result)


# ============================================================
# 任务
# ============================================================

@router.post("/tasks", response_model=VideoGenerationJobOut, status_code=202, summary="创建视频生成任务")
def create_task(
    project_id: str,
    payload: VideoGenerationJobCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VideoGenerationJob:
    _get_owned_project(db, project_id, current)

    # 幂等键
    if payload.idempotency_key:
        existing = (
            db.query(VideoGenerationJob)
            .filter(
                VideoGenerationJob.project_id == project_id,
                VideoGenerationJob.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if existing:
            return _job_to_out(existing)

    # 用户必须明确选择首帧
    first_asset = db.get(Asset, payload.first_frame_asset_id)
    if not first_asset or first_asset.project_id != project_id or first_asset.asset_type != "image":
        raise ConflictError("请先在素材库明确选择一张首帧图片，再发起图生视频。")

    # 用户选择的视频 Provider（留空用全局默认）；未配置 Key 直接报错，不静默降级
    chosen_provider = (payload.provider or "").strip().lower() or None
    if chosen_provider:
        adapter = build_video_adapter(chosen_provider)
        if adapter is None or not adapter.is_available():
            raise ConflictError(
                f"视频 Provider「{chosen_provider}」未配置 API Key 或不可用，请在 .env 配置后重试。"
            )
    else:
        adapter = get_video_adapter()

    mode = payload.generation_mode
    if mode == "image_to_video" and not adapter.supports("image_to_video"):
        raise ConflictError(f"视频 Provider「{adapter.provider}」不支持图生视频。")

    last_asset = None
    if mode == "first_last_frame_video":
        if not payload.last_frame_asset_id:
            raise ConflictError("首尾帧模式必须明确选择两张图片：第一张为首帧，第二张为尾帧。")
        last_asset = db.get(Asset, payload.last_frame_asset_id)
        if not last_asset or last_asset.project_id != project_id or last_asset.asset_type != "image":
            raise ConflictError("尾帧必须为当前项目中的图片素材。")
        # Provider 不支持首尾帧时禁用，不允许降级成普通图生视频
        if not adapter.supports("first_last_frame_video"):
            raise ConflictError(
                f"视频 Provider「{adapter.provider}」不支持首尾帧模式，且不允许降级为普通图生视频。"
                "可改用 Seedance 2.0 或切换为图生视频模式。"
            )

    # 分镜归属校验
    if payload.storyboard_shot_id:
        shot = db.get(StoryboardShot, payload.storyboard_shot_id)
        if not shot or shot.project_id != project_id:
            raise NotFoundError("分镜不存在或不属于当前项目")

    # 模板校验（不存在或停用则忽略模板，但不阻断）
    if payload.template_id:
        t = db.get(VideoGenerationTemplate, payload.template_id)
        if not t or not t.is_enabled:
            raise NotFoundError("视频模板不存在或已停用")

    # 冲突拦截
    conflicts = check_arch_conflicts(payload.positive_prompt or "")
    if conflicts:
        raise ConflictError(
            "检测到可能改变工程结构的请求：" + "、".join(conflicts) +
            "。禁止增加楼层、改变建筑轮廓、移动道路或替换主楼等结构性修改。"
        )

    try:
        job = create_video_job(
            db=db,
            project_id=project_id,
            storyboard_shot_id=payload.storyboard_shot_id,
            generation_mode=mode,
            first_frame_asset_id=payload.first_frame_asset_id,
            last_frame_asset_id=payload.last_frame_asset_id,
            template_id=payload.template_id,
            positive_prompt=payload.positive_prompt,
            negative_prompt=payload.negative_prompt,
            duration=payload.duration,
            aspect_ratio=payload.aspect_ratio,
            resolution=payload.resolution,
            seed=payload.seed,
            generate_audio=payload.generate_audio,
            constraints_enabled=payload.constraints_enabled,
            idempotency_key=payload.idempotency_key,
            created_by=current.username,
            provider=chosen_provider,
            model_name=payload.model_name,
        )
    except ValueError as exc:
        raise ConflictError(str(exc))

    _dispatch_video_job(db, job)
    db.refresh(job)
    return _job_to_out(job)


@router.get("/tasks", response_model=list[VideoGenerationJobOut], summary="任务列表")
def list_tasks(
    project_id: str,
    status: str | None = None,
    shot_id: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    query = db.query(VideoGenerationJob).filter(VideoGenerationJob.project_id == project_id)
    if status:
        query = query.filter(VideoGenerationJob.status == status)
    if shot_id:
        query = query.filter(VideoGenerationJob.storyboard_shot_id == shot_id)
    jobs = query.order_by(VideoGenerationJob.created_at.desc()).limit(100).all()
    return [_job_to_out(j) for j in jobs]


@router.get("/tasks/{job_id}", response_model=VideoGenerationJobOut, summary="任务详情（轮询）")
def get_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    job = db.get(VideoGenerationJob, job_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("视频生成任务不存在")
    return _job_to_out(job)


@router.post("/tasks/{job_id}/retry", response_model=VideoGenerationJobOut, summary="重试失败任务")
def retry_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    job = db.get(VideoGenerationJob, job_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("视频生成任务不存在")
    if job.status in ("success", "running"):
        raise ConflictError("仅失败或已取消任务可重试")
    job.status = "queued"
    job.error_message = None
    job.progress = 0
    job.provider_task_id = None
    db.commit()
    _dispatch_video_job(db, job)
    db.refresh(job)
    return _job_to_out(job)


@router.post("/tasks/{job_id}/cancel", response_model=VideoGenerationJobOut, summary="取消任务")
def cancel_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    job = db.get(VideoGenerationJob, job_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("视频生成任务不存在")
    if job.status in ("queued", "running"):
        # 尝试取消 Provider 任务（Seedance DELETE 支持）
        if job.provider_task_id:
            adapter = build_video_adapter(job.provider) or get_video_adapter()
            try:
                if adapter.supports("cancel_task"):
                    adapter.cancel_task(job.provider_task_id)
            except Exception:
                pass
        job.status = "cancelled"
        job.error_message = None
        db.commit()
    db.refresh(job)
    return _job_to_out(job)


@router.get("/tasks/{job_id}/versions", response_model=list[VideoGenerationVersionOut], summary="任务结果版本")
def task_versions(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    job = db.get(VideoGenerationJob, job_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("视频生成任务不存在")
    versions = (
        db.query(VideoGenerationVersion)
        .filter(
            VideoGenerationVersion.video_job_id == job_id,
            VideoGenerationVersion.is_deleted.is_(False),
        )
        .order_by(VideoGenerationVersion.version_number.asc())
        .all()
    )
    return [_version_to_out(v) for v in versions]


# ============================================================
# 版本管理
# ============================================================

@router.get("/versions", response_model=list[VideoGenerationVersionOut], summary="项目视频版本列表")
def list_versions(
    project_id: str,
    shot_id: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    query = db.query(VideoGenerationVersion).filter(VideoGenerationVersion.is_deleted.is_(False))
    if shot_id:
        query = query.filter(VideoGenerationVersion.bound_shot_id == shot_id)
    else:
        job_ids = (
            db.query(VideoGenerationJob.id)
            .filter(VideoGenerationJob.project_id == project_id)
            .all()
        )
        job_ids = [j[0] for j in job_ids]
        if not job_ids:
            return []
        query = query.filter(VideoGenerationVersion.video_job_id.in_(job_ids))
    versions = query.order_by(VideoGenerationVersion.created_at.desc()).limit(200).all()
    return [_version_to_out(v) for v in versions]


@router.post("/versions/{version_id}/select", response_model=VideoGenerationVersionOut, summary="选为当前结果")
def select_result(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    try:
        version = select_version(db, project_id, version_id, current.username)
    except RuntimeError as exc:
        raise ConflictError(str(exc))
    return _version_to_out(version)


@router.post("/versions/{version_id}/bind", response_model=dict, summary="绑定到分镜")
def bind_shot(
    project_id: str,
    version_id: str,
    payload: BindToShotRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_owned_project(db, project_id, current)
    try:
        return bind_version_to_shot(
            db, project_id, version_id, payload.shot_id, current.username
        )
    except RuntimeError as exc:
        raise ConflictError(str(exc))


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
