"""AI 视频生成 API（Phase 6/7：Seedance 图片驱动视频素材）。

独立于「解说词与分镜」页面的视频生成模块：
- 模板列表 / 管理（42 个内置 + 企业自定义）
- 创建/查询/取消/重试视频生成任务
- 结果版本管理（预览/下载/选为当前结果/删除）
- 建筑约束冲突预检
"""

from __future__ import annotations

import time
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.factory import (
    build_video_adapter,
    get_video_adapter,
    video_providers_info,
)
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.services.permissions import (
    get_project_access,
    PERM_MEDIA_EDIT,
    PERM_MEDIA_VIEW,
)
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.api.v1.video_gen_support import (
    draft_to_out,
    job_to_out,
    prompt_master_mock_allowed,
    template_to_out,
    version_to_out,
)
from app.core.logging import get_logger
from app.models.asset import Asset
from app.models.project import Project
from app.models.user import User
from app.models.video_generation import (
    VideoGenerationJob,
    VideoGenerationTemplate,
    VideoGenerationVersion,
    VideoTemplateDraft,
)
from app.schemas.video_gen import (
    ConstraintCheckRequest,
    ConstraintCheckResult,
    PromptCompileRequest,
    PromptCompileResult,
    PromptMasterRequest,
    PromptMasterResult,
    ReferenceImageOut,
    VideoTemplateDraftAnalyzeRequest,
    VideoTemplateDraftClipRequest,
    VideoTemplateDraftCreate,
    VideoTemplateDraftOut,
    VideoTemplateDraftRecipeUpdate,
    VideoTemplatePreviewRequest,
    VideoTemplatePublishRequest,
    VideoGenerationJobCreate,
    VideoGenerationJobOut,
    VideoGenerationTemplateCreate,
    VideoGenerationTemplateOut,
    VideoGenerationTemplateUpdate,
    VideoGenerationVersionOut,
    VideoGenerationVersionRenameRequest,
)
from app.services.video_gen_service import (
    SEEDANCE_PROMPT_LIMIT,
    build_provider_prompt,
    build_reference_timing,
    check_arch_conflicts,
    compile_video_prompts,
    create_video_job,
    generate_prompt_master,
    normalize_video_duration,
    run_video_job,
    seed_video_generation_templates,
    select_version,
    soft_delete_version,
)
from app.services.video_template_service import (
    clone_template_reference_assets,
    extract_template_frames,
    inspect_source_video,
)
from app.services.construction_prompt import normalize_construction_recipe
from app.services.video_gen_templates import ARCH_CONSTRAINTS, ARCH_NEGATIVE
from app.tasks.video_gen import video_gen_job_task

router = APIRouter(prefix="/projects/{project_id}/ai-video", tags=["AI 视频生成"])

logger = get_logger(__name__)


_prompt_master_mock_allowed = prompt_master_mock_allowed

# ---------------- 辅助 ----------------

def _get_owned_project(db: Session, project_id: str, user: User, permission: str = PERM_MEDIA_VIEW) -> Project:
    """统一项目访问：成员校验 + 细粒度权限（非成员 404，权限不足 403）。"""
    return get_project_access(db, project_id, user, permission).project


def _run_video_job_background(job_id: str) -> None:
    try:
        run_video_job(job_id)
    except Exception:
        logger.exception("video_gen_background_job_failed", job_id=job_id)


def _start_video_job_thread(job_id: str) -> None:
    threading.Thread(
        target=_run_video_job_background,
        args=(job_id,),
        name=f"video-gen-{job_id[:8]}",
        daemon=True,
    ).start()


def _dispatch_video_job(db: Session, job: VideoGenerationJob) -> None:
    """分发任务：真实 Provider 始终异步，Mock 保持同步以便本地演示和测试。"""
    if settings.use_celery:
        try:
            # Redis 可用并不代表存在消费者。没有 worker 时 delay() 仍会成功，
            # 任务却会永久停在队列起始进度，因此先做一次轻量存活检查。
            workers = video_gen_job_task.app.control.ping(timeout=0.5)
            if not workers:
                raise RuntimeError("Celery worker 未运行")
            async_result = video_gen_job_task.delay(job.id)
            job.celery_task_id = async_result.id
            db.commit()
        except Exception as exc:
            logger.warning("celery_video_gen_fallback_thread", error=str(exc))
            _start_video_job_thread(job.id)
    else:
        if job.provider == "mock":
            try:
                run_video_job(job.id)
            except Exception:
                pass
            return
        _start_video_job_thread(job.id)


def _refresh_draft_preview_status(db: Session, draft: VideoTemplateDraft) -> None:
    if not draft.preview_job_id:
        return
    job = db.get(VideoGenerationJob, draft.preview_job_id)
    if not job:
        return
    if job.status == "success" and job.result_asset_id:
        draft.preview_asset_id = job.result_asset_id
        draft.status = "ready"
        db.commit()
        db.refresh(draft)
    elif job.status == "failed":
        draft.status = "preview_failed"
        db.commit()


# ============================================================
# 模板
# ============================================================

@router.get("/templates", response_model=list[VideoGenerationTemplateOut], summary="视频模板列表")
def list_templates(
    project_id: str,
    mode: str | None = None,
    scope: str = "all",
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    query = db.query(VideoGenerationTemplate).filter(VideoGenerationTemplate.is_enabled.is_(True))
    if scope == "personal":
        query = query.filter(
            VideoGenerationTemplate.is_system.is_(False),
            VideoGenerationTemplate.scope == "personal",
            VideoGenerationTemplate.created_by == current.username,
        )
    elif scope == "organization":
        query = query.filter(
            or_(
                VideoGenerationTemplate.is_system.is_(True),
                VideoGenerationTemplate.scope == "organization",
            )
        )
    elif scope != "all":
        raise HTTPException(status_code=422, detail="模板范围只能是 all、personal 或 organization")
    else:
        # 个人模板只对创建者可见，企业模板和系统模板对项目成员可见。
        query = query.filter(
            or_(
                VideoGenerationTemplate.is_system.is_(True),
                VideoGenerationTemplate.scope == "organization",
                and_(
                    VideoGenerationTemplate.scope == "personal",
                    VideoGenerationTemplate.created_by == current.username,
                ),
            )
        )
    templates = query.order_by(
        VideoGenerationTemplate.is_system.desc(),
        VideoGenerationTemplate.sort_order.asc(),
    ).all()
    if mode:
        templates = [
            t for t in templates
            if t.applicable_modes and (mode in (t.applicable_modes or []) or (mode == "multi_reference_video" and "image_to_video" in (t.applicable_modes or [])))
        ]
    return [template_to_out(t) for t in templates]


@router.get("/templates/{template_id}", response_model=VideoGenerationTemplateOut, summary="模板详情")
def get_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    t = db.get(VideoGenerationTemplate, template_id)
    if not t or not t.is_enabled:
        raise NotFoundError("模板不存在")
    return template_to_out(t)


@router.post("/templates", response_model=VideoGenerationTemplateOut, status_code=201, summary="创建企业模板")
def create_template(
    project_id: str,
    payload: VideoGenerationTemplateCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
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
        category=payload.category,
        tags=payload.tags,
        prompt_recipe=normalize_construction_recipe(payload.prompt_recipe),
        preview_asset_id=payload.preview_asset_id,
        cover_asset_id=payload.cover_asset_id,
        reference_frame_asset_ids=payload.reference_frame_asset_ids,
        reference_frame_times=payload.reference_frame_times,
        reference_frame_count=payload.reference_frame_count,
        scope=payload.scope,
        status="published",
        is_system=False,
        is_enabled=payload.is_enabled,
        created_by=current.username,
        sort_order=100,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return template_to_out(t)


@router.patch("/templates/{template_id}", response_model=VideoGenerationTemplateOut, summary="更新模板")
def update_template(
    project_id: str,
    template_id: str,
    payload: VideoGenerationTemplateUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    t = db.get(VideoGenerationTemplate, template_id)
    if not t:
        raise NotFoundError("模板不存在")
    if t.is_system and not current.is_superuser:
        raise ForbiddenError("系统模板仅管理员可修改")
    data = payload.model_dump(exclude_unset=True)
    if "prompt_recipe" in data:
        data["prompt_recipe"] = normalize_construction_recipe(data["prompt_recipe"])
    for field, value in data.items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return template_to_out(t)


@router.delete("/templates/{template_id}", status_code=204, summary="删除模板")
def delete_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    t = db.get(VideoGenerationTemplate, template_id)
    if not t:
        raise NotFoundError("模板不存在")
    if t.is_system:
        raise ForbiddenError("系统模板不可删除，可停用")
    if not current.is_superuser and t.created_by != current.username:
        raise ForbiddenError("只能删除自己创建的模板")
    db.delete(t)
    db.commit()


# ============================================================
# 从专业视频创建模板
# ============================================================

def _get_owned_template_draft(db: Session, project_id: str, draft_id: str) -> VideoTemplateDraft:
    draft = db.get(VideoTemplateDraft, draft_id)
    if not draft or draft.project_id != project_id:
        raise NotFoundError("模板草稿不存在")
    return draft


@router.post("/template-drafts", response_model=VideoTemplateDraftOut, status_code=201, summary="创建视频模板草稿")
def create_template_draft(
    project_id: str,
    payload: VideoTemplateDraftCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    source = db.get(Asset, payload.source_video_asset_id)
    if not source or source.project_id != project_id or source.asset_type != "video":
        raise NotFoundError("模板来源视频不存在")
    try:
        inspect_source_video(db, source)
    except (ValueError, RuntimeError) as exc:
        raise ConflictError(str(exc)) from exc
    draft = VideoTemplateDraft(
        project_id=project_id,
        source_video_asset_id=source.id,
        name=payload.name.strip(),
        description=payload.description,
        status="uploaded",
        # 保留字段用于兼容已有数据；创建流程不再阻断用户确认使用权。
        source_license_confirmed=bool(payload.source_license_confirmed),
        created_by=current.username,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft_to_out(db, draft)


@router.get("/template-drafts", response_model=list[VideoTemplateDraftOut], summary="模板草稿列表")
def list_template_drafts(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    drafts = (
        db.query(VideoTemplateDraft)
        .filter(
            VideoTemplateDraft.project_id == project_id,
            VideoTemplateDraft.created_by == current.username,
        )
        .order_by(VideoTemplateDraft.updated_at.desc())
        .limit(20)
        .all()
    )
    return [draft_to_out(db, draft) for draft in drafts]


@router.get("/template-drafts/{draft_id}", response_model=VideoTemplateDraftOut, summary="模板草稿详情")
def get_template_draft(
    project_id: str,
    draft_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    draft = _get_owned_template_draft(db, project_id, draft_id)
    _refresh_draft_preview_status(db, draft)
    return draft_to_out(db, draft)


@router.post("/template-drafts/{draft_id}/clip", response_model=VideoTemplateDraftOut, summary="截取模板镜头并提取关键帧")
def clip_template_draft(
    project_id: str,
    draft_id: str,
    payload: VideoTemplateDraftClipRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    draft = _get_owned_template_draft(db, project_id, draft_id)
    try:
        extract_template_frames(
            db,
            draft,
            clip_start=payload.clip_start_seconds,
            clip_end=payload.clip_end_seconds,
            middle=payload.middle_seconds,
        )
    except (ValueError, RuntimeError) as exc:
        raise ConflictError(str(exc)) from exc
    return draft_to_out(db, draft)


@router.post("/template-drafts/{draft_id}/analyze", response_model=VideoTemplateDraftOut, summary="AI 提炼模板配方")
def analyze_template_draft(
    project_id: str,
    draft_id: str,
    payload: VideoTemplateDraftAnalyzeRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    draft = _get_owned_template_draft(db, project_id, draft_id)
    if not draft.first_frame_asset_id:
        raise ConflictError("请先截取镜头并提取首帧")
    if payload.generation_mode == "first_last_frame_video" and not draft.last_frame_asset_id:
        raise ConflictError("首尾帧模式需要先提取尾帧")
    if payload.generation_mode == "multi_reference_video" and (
        not draft.middle_frame_asset_id or not draft.last_frame_asset_id
    ):
        raise ConflictError("多参考图模式需要先提取首帧、中间帧和尾帧")
    draft.intent = (payload.intent or "").strip() or None
    selected_reference_ids = list(draft.reference_frame_asset_ids or [])
    if payload.generation_mode == "image_to_video":
        selected_reference_ids = [draft.first_frame_asset_id]
    elif payload.generation_mode == "first_last_frame_video":
        selected_reference_ids = [draft.first_frame_asset_id, draft.last_frame_asset_id]
    elif len(selected_reference_ids) < 2:
        selected_reference_ids = [
            asset_id for asset_id in (
                draft.first_frame_asset_id,
                draft.middle_frame_asset_id,
                draft.last_frame_asset_id,
            ) if asset_id
        ]
    selected_reference_ids = list(dict.fromkeys(selected_reference_ids))
    reference_timing = build_reference_timing(
        clip_start_seconds=draft.clip_start_seconds,
        clip_end_seconds=draft.clip_end_seconds,
        reference_frame_times=draft.reference_frame_times,
        generation_mode=payload.generation_mode,
    )
    result = generate_prompt_master(
        db,
        project_id,
        first_frame_asset_id=selected_reference_ids[0],
        middle_frame_asset_id=None,
        last_frame_asset_id=None,
        reference_asset_ids=selected_reference_ids[1:],
        template_id=None,
        intent=draft.intent,
        generation_mode=payload.generation_mode,
        reference_timing_seconds=reference_timing["reference_timing_seconds"],
        clip_duration_seconds=reference_timing["clip_duration_seconds"],
        require_real_ai=not _prompt_master_mock_allowed(),
    )
    raw_recipe = result.get("recipe")
    recipe = dict(raw_recipe) if isinstance(raw_recipe, dict) else {}
    recipe["prompt"] = result.get("prompt") or ""
    recipe["negative_prompt"] = result.get("negative_prompt") or ARCH_NEGATIVE
    # 视觉模型有时会把 recommended 生成为数组（例如 ["平滑过渡"]），
    # 但模板配方在后续流程中需要用对象写入 duration。统一归一化，避免
    # 生成成功后在这里因 list[key] 触发 500。
    recommended = recipe.get("recommended")
    if not isinstance(recommended, dict):
        recommended = {}
        recipe["recommended"] = recommended
    if result.get("recommended_duration"):
        recommended["duration"] = result["recommended_duration"]
    recipe["reference_timing_seconds"] = reference_timing["reference_timing_seconds"]
    recipe["clip_duration_seconds"] = reference_timing["clip_duration_seconds"]
    if reference_timing["clip_duration_seconds"]:
        # 模板选择的片段长度是参考图时序的时间基准，发布到模板库后也保持一致。
        recommended["duration"] = max(
            2,
            min(15, int(round(reference_timing["clip_duration_seconds"]))),
        )
    # 参考帧数量由用户在关键帧步骤明确选择，不能被视觉模型返回的模式覆盖。
    recipe["generation_modes"] = [payload.generation_mode]
    generated_name = str(result.get("name") or "").strip()
    generated_description = str(result.get("description") or "").strip()
    if generated_name:
        draft.name = generated_name[:128]
    if generated_description:
        draft.description = generated_description[:2000]
    draft.prompt_recipe = recipe
    draft.analysis_warnings = list(result.get("warnings") or [])
    draft.status = "analyzed"
    db.commit()
    db.refresh(draft)
    return draft_to_out(db, draft)


@router.patch("/template-drafts/{draft_id}/recipe", response_model=VideoTemplateDraftOut, summary="修改模板配方")
def update_template_draft_recipe(
    project_id: str,
    draft_id: str,
    payload: VideoTemplateDraftRecipeUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    draft = _get_owned_template_draft(db, project_id, draft_id)
    if payload.name is not None:
        draft.name = payload.name.strip()
    if payload.description is not None:
        draft.description = payload.description
    draft.prompt_recipe = normalize_construction_recipe(payload.prompt_recipe)
    draft.status = "analyzed"
    db.commit()
    db.refresh(draft)
    return draft_to_out(db, draft)


@router.post("/template-drafts/{draft_id}/preview", response_model=VideoGenerationJobOut, status_code=202, summary="试生成模板视频")
def preview_template_draft(
    project_id: str,
    draft_id: str,
    payload: VideoTemplatePreviewRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    draft = _get_owned_template_draft(db, project_id, draft_id)
    recipe = normalize_construction_recipe(draft.prompt_recipe) or {}
    prompt = str(recipe.get("prompt") or "").strip()
    if not prompt:
        raise ConflictError("请先完成 AI 提炼或填写模板提示词")
    requested_modes = recipe.get("generation_modes")
    requested_mode = requested_modes[0] if isinstance(requested_modes, list) and requested_modes else None
    generation_mode = requested_mode if requested_mode in {
        "image_to_video", "first_last_frame_video", "multi_reference_video"
    } else "image_to_video"
    if not draft.first_frame_asset_id:
        raise ConflictError("请先提取首帧")
    if generation_mode == "first_last_frame_video" and not draft.last_frame_asset_id:
        raise ConflictError("首尾帧模式需要先提取尾帧")
    if generation_mode == "multi_reference_video" and (
        not draft.middle_frame_asset_id or not draft.last_frame_asset_id
    ):
        raise ConflictError("多参考图模式需要先提取首帧、中间帧和尾帧")
    preview_reference_asset_ids = list(draft.reference_frame_asset_ids or [])
    if generation_mode == "image_to_video":
        preview_reference_asset_ids = [draft.first_frame_asset_id]
    elif generation_mode == "first_last_frame_video":
        preview_reference_asset_ids = [draft.first_frame_asset_id, draft.last_frame_asset_id]
    elif len(preview_reference_asset_ids) < 2:
        preview_reference_asset_ids = [
            asset_id for asset_id in (
                draft.first_frame_asset_id,
                draft.middle_frame_asset_id,
                draft.last_frame_asset_id,
            ) if asset_id
        ]
    preview_reference_asset_ids = list(dict.fromkeys(preview_reference_asset_ids))
    preview_last_frame_asset_id = (
        draft.last_frame_asset_id if generation_mode == "first_last_frame_video" else None
    )
    reference_timing = build_reference_timing(
        clip_start_seconds=draft.clip_start_seconds,
        clip_end_seconds=draft.clip_end_seconds,
        reference_frame_times=draft.reference_frame_times,
        generation_mode=generation_mode,
    )
    # 即使配方是在旧版本中生成，也要把当前草稿的相对时序带入本次试生成。
    recipe["reference_timing_seconds"] = reference_timing["reference_timing_seconds"]
    recipe["clip_duration_seconds"] = reference_timing["clip_duration_seconds"]
    recommended = recipe.get("recommended") if isinstance(recipe.get("recommended"), dict) else {}
    fallback_duration = max(2, min(15, int(round(reference_timing["clip_duration_seconds"] or 5))))
    duration = payload.duration or normalize_video_duration(recommended.get("duration"), fallback_duration)
    try:
        job = create_video_job(
            db=db,
            project_id=project_id,
            generation_mode=generation_mode,
            first_frame_asset_id=draft.first_frame_asset_id,
            last_frame_asset_id=preview_last_frame_asset_id,
            reference_asset_ids=preview_reference_asset_ids if generation_mode == "multi_reference_video" else [],
            template_id=None,
            positive_prompt=prompt,
            negative_prompt=str(recipe.get("negative_prompt") or ARCH_NEGATIVE),
            duration=duration,
            aspect_ratio=payload.aspect_ratio,
            resolution=payload.resolution,
            seed=None,
            generate_audio=False,
            constraints_enabled=True,
            idempotency_key=f"template-preview-{draft.id}-{uuid.uuid4().hex[:10]}",
            created_by=current.username,
            provider=payload.provider,
            model_name=payload.model_name,
            prompt_recipe=recipe,
            structure_conflict_confirmed=payload.structure_conflict_confirmed,
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    job.parameter_snapshot = {
        **(job.parameter_snapshot or {}),
        "template_draft_id": draft.id,
        "template_preview": True,
        "template_recipe": recipe,
    }
    draft.preview_job_id = job.id
    draft.status = "previewing"
    db.commit()
    _dispatch_video_job(db, job)
    db.refresh(job)
    return job_to_out(job)


@router.post("/template-drafts/{draft_id}/publish", response_model=VideoGenerationTemplateOut, status_code=201, summary="发布视频模板")
def publish_template_draft(
    project_id: str,
    draft_id: str,
    payload: VideoTemplatePublishRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    draft = _get_owned_template_draft(db, project_id, draft_id)
    _refresh_draft_preview_status(db, draft)
    preview_job = db.get(VideoGenerationJob, draft.preview_job_id) if draft.preview_job_id else None
    if not preview_job or preview_job.status != "success" or not preview_job.result_asset_id:
        raise ConflictError("请先完成一次成功的试生成，试生成视频会自动进入素材库")
    recipe = normalize_construction_recipe(draft.prompt_recipe) or {}
    recommended = recipe.get("recommended") if isinstance(recipe.get("recommended"), dict) else {}
    modes = recipe.get("generation_modes") or ["first_last_frame_video"]
    constraints = recipe.get("preserve") or ARCH_CONSTRAINTS
    template = VideoGenerationTemplate(
        name=(payload.name or draft.name).strip(),
        description=payload.description if payload.description is not None else draft.description,
        applicable_modes=list(modes),
        default_positive_prompt=str(recipe.get("prompt") or ""),
        default_negative_prompt=str(recipe.get("negative_prompt") or ARCH_NEGATIVE),
        recommended_duration=normalize_video_duration(recommended.get("duration"), 5),
        recommended_aspect_ratio=str(recommended.get("aspect_ratio") or "adaptive"),
        recommended_resolution=str(recommended.get("resolution") or "720p"),
        recommended_camera_motion=str((recipe.get("camera") or {}).get("type") or "稳定运镜"),
        default_arch_constraints=list(constraints),
        is_system=False,
        is_enabled=True,
        created_by=current.username,
        sort_order=1000,
        category=payload.category,
        tags=list(payload.tags or recipe.get("tags") or []),
        prompt_recipe=recipe,
        preview_asset_id=preview_job.result_asset_id,
        cover_asset_id=None,
        reference_frame_asset_ids=[],
        reference_frame_times=[float(value) for value in (draft.reference_frame_times or [])],
        reference_frame_count=0,
        scope=payload.scope,
        status="published",
        source_video_asset_id=draft.source_video_asset_id,
        clip_start_seconds=draft.clip_start_seconds,
        clip_end_seconds=draft.clip_end_seconds,
        first_frame_asset_id=None,
        middle_frame_asset_id=None,
        last_frame_asset_id=None,
        source_license_confirmed=draft.source_license_confirmed,
    )
    db.add(template)
    db.flush()
    source_reference_ids = list(draft.reference_frame_asset_ids or [])
    if not source_reference_ids:
        source_reference_ids = list(dict.fromkeys(
            asset_id for asset_id in (
                draft.first_frame_asset_id,
                draft.middle_frame_asset_id,
                draft.last_frame_asset_id,
            ) if asset_id
        ))
    try:
        template_reference_ids = clone_template_reference_assets(
            db,
            project_id=project_id,
            template_id=template.id,
            reference_asset_ids=source_reference_ids,
            reference_times=[float(value) for value in (draft.reference_frame_times or [])],
        )
    except ValueError as exc:
        db.rollback()
        raise ConflictError(str(exc)) from exc
    if not template_reference_ids:
        db.rollback()
        raise ConflictError("模板没有可用的参考帧，请返回关键帧步骤重新提取")
    template.reference_frame_asset_ids = template_reference_ids
    template.reference_frame_count = len(template_reference_ids)
    template.cover_asset_id = template_reference_ids[0]
    template.first_frame_asset_id = template_reference_ids[0]
    template.middle_frame_asset_id = (
        template_reference_ids[len(template_reference_ids) // 2]
        if len(template_reference_ids) > 2 else None
    )
    template.last_frame_asset_id = (
        template_reference_ids[-1] if len(template_reference_ids) > 1 else None
    )
    draft.template_id = template.id
    draft.preview_asset_id = preview_job.result_asset_id
    draft.status = "published"
    db.commit()
    db.refresh(template)
    return template_to_out(template)


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
    if provider not in ("seedance", "mock"):
        return {cap: False for cap in _ALL_VIDEO_CAPS}
    adapter = build_video_adapter(provider) or get_video_adapter()
    if provider == "mock" or provider == adapter.provider:
        return adapter.capabilities()
    return {cap: False for cap in _ALL_VIDEO_CAPS}


_ALL_VIDEO_CAPS = [
    "text_to_video", "image_to_video", "first_last_frame_video",
    "multi_reference_video",
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
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
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
    conflict_text = str(
        (payload.prompt_recipe or {}).get("provider_prompt_override")
        or payload.text
        or ""
    )
    conflicts = check_arch_conflicts(conflict_text, payload.prompt_recipe)
    return ConstraintCheckResult(conflicts=conflicts, blocked=bool(conflicts))


@router.post("/compile-prompt", response_model=PromptCompileResult, summary="编译最终视频提示词")
def compile_prompt(
    project_id: str,
    payload: PromptCompileRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回与实际视频任务完全相同的 Seedance 提示词编译结果。"""
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    recipe = payload.prompt_recipe
    arch_constraints: list[str] | None = None
    if payload.template_id:
        template = db.get(VideoGenerationTemplate, payload.template_id)
        if template and template.is_enabled:
            arch_constraints = template.default_arch_constraints or ARCH_CONSTRAINTS
    conflict_text = str((recipe or {}).get("provider_prompt_override") or payload.positive_prompt or "")
    conflicts = check_arch_conflicts(conflict_text, recipe)
    positive, negative, normalized = compile_video_prompts(
        positive_prompt=payload.positive_prompt,
        negative_prompt=payload.negative_prompt,
        prompt_recipe=recipe,
        constraints_enabled=payload.constraints_enabled,
        arch_constraints=arch_constraints,
        resolution=payload.resolution,
    )
    provider_prompt = build_provider_prompt(positive, negative)
    return PromptCompileResult(
        positive_prompt=positive,
        negative_prompt=negative,
        provider_prompt=provider_prompt,
        provider_prompt_chars=len(provider_prompt),
        provider_prompt_limit=SEEDANCE_PROMPT_LIMIT,
        prompt_recipe=normalized,
        conflicts=conflicts,
        blocked=bool(conflicts),
    )


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
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    ids = [i for i in (payload.first_frame_asset_id, payload.last_frame_asset_id) if i]
    ids += payload.reference_asset_ids or []
    if not [i for i in ids if i]:
        raise HTTPException(status_code=400, detail="请先选择至少一张参考帧图片")
    result = generate_prompt_master(
        db,
        project_id,
        first_frame_asset_id=payload.first_frame_asset_id,
        middle_frame_asset_id=payload.middle_frame_asset_id,
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
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)

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
            return job_to_out(existing)

    # 用户必须明确选择首帧
    first_asset = db.get(Asset, payload.first_frame_asset_id)
    if not first_asset or first_asset.project_id != project_id or first_asset.asset_type != "image":
        raise ConflictError("请先在素材库明确选择一张首帧图片，再发起图生视频。")

    # 用户选择的视频 Provider（留空用全局默认）；未配置 Key 直接报错，不静默降级
    chosen_provider = (payload.provider or "").strip().lower() or None
    if chosen_provider and chosen_provider not in ("seedance", "mock"):
        raise ConflictError("当前新建视频任务仅开放 Seedance，请刷新页面后重新提交。")
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

    reference_ids = list(dict.fromkeys(payload.reference_asset_ids or []))
    if mode == "multi_reference_video":
        # 首帧字段保留用于旧客户端兼容，但真正的顺序以 reference_asset_ids 为准。
        if len(reference_ids) < 2 or len(reference_ids) > 9:
            raise ConflictError("多参考图模式需要按顺序选择 2~9 张图片。")
        if payload.first_frame_asset_id and reference_ids[0] != payload.first_frame_asset_id:
            raise ConflictError("多参考图模式中，首帧必须与第一张参考图一致。")
        if not adapter.supports("multi_reference_video"):
            raise ConflictError(f"视频 Provider「{adapter.provider}」不支持多参考图模式，请使用 Seedance 2.0。")
        requested_model = (payload.model_name or getattr(adapter, "config", {}).get("model") or "").lower()
        if requested_model and ("seedance-2" not in requested_model and "seedance_2" not in requested_model):
            raise ConflictError("多参考图模式需要 Seedance 2.0 或 2.0 Fast 模型，请切换模型后再提交。")
        ref_assets = [db.get(Asset, aid) for aid in reference_ids]
        if any(not a or a.project_id != project_id or a.asset_type != "image" for a in ref_assets):
            raise ConflictError("所有参考图必须来自当前项目的图片素材。")

    # 模板校验：模板、模式必须匹配，避免前端选了模板但后端静默忽略。
    if payload.template_id:
        t = db.get(VideoGenerationTemplate, payload.template_id)
        if not t or not t.is_enabled:
            raise NotFoundError("视频模板不存在或已停用")
        if not t.is_system and t.scope == "personal" and t.created_by != current.username:
            raise ForbiddenError("个人模板只能由创建者使用")
        template_modes = list(t.applicable_modes or [])
        # 多图模板是“参考图模板”，本次生成仍可按用户选择走单图、首尾帧或多图。
        if "multi_reference_video" in template_modes:
            template_modes = [
                "image_to_video",
                "first_last_frame_video",
                "multi_reference_video",
            ]
        # 旧的单图模板继续兼容 Seedance 2.0 多参考图扩展。
        elif mode == "multi_reference_video" and "image_to_video" in template_modes:
            template_modes.append(mode)
        if template_modes and mode not in template_modes:
            raise ConflictError("当前模板不支持所选生成模式，请更换模板或模式。")

    # 冲突拦截
    recipe_for_conflict = payload.prompt_recipe
    if not recipe_for_conflict and payload.template_id:
        selected_template = db.get(VideoGenerationTemplate, payload.template_id)
        recipe_for_conflict = selected_template.prompt_recipe if selected_template else None
    conflict_text = str(
        (recipe_for_conflict or {}).get("provider_prompt_override")
        or payload.positive_prompt
        or ""
    )
    conflicts = check_arch_conflicts(conflict_text, recipe_for_conflict)
    if conflicts and not payload.structure_conflict_confirmed:
        raise ConflictError(
            "检测到可能改变工程结构的请求：" + "、".join(conflicts) +
            "。禁止增加楼层、改变建筑轮廓、移动道路或替换主楼等结构性修改。"
        )

    try:
        job = create_video_job(
            db=db,
            project_id=project_id,
            generation_mode=mode,
            first_frame_asset_id=payload.first_frame_asset_id,
            last_frame_asset_id=payload.last_frame_asset_id,
            reference_asset_ids=reference_ids,
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
            variant_group_id=str(uuid.uuid4()),
            prompt_recipe=payload.prompt_recipe,
            structure_conflict_confirmed=payload.structure_conflict_confirmed,
        )
    except IntegrityError:
        db.rollback()
        if not payload.idempotency_key:
            raise
        existing = (
            db.query(VideoGenerationJob)
            .filter(
                VideoGenerationJob.project_id == project_id,
                VideoGenerationJob.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if not existing:
            raise
        return job_to_out(existing)
    except ValueError as exc:
        raise ConflictError(str(exc))

    _dispatch_video_job(db, job)
    db.refresh(job)
    return job_to_out(job)


@router.get("/tasks", response_model=list[VideoGenerationJobOut], summary="任务列表")
def list_tasks(
    project_id: str,
    status: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    query = db.query(VideoGenerationJob).filter(VideoGenerationJob.project_id == project_id)
    if status:
        query = query.filter(VideoGenerationJob.status == status)
    jobs = query.order_by(VideoGenerationJob.created_at.desc()).limit(100).all()
    return [job_to_out(j) for j in jobs]


@router.get("/tasks/{job_id}", response_model=VideoGenerationJobOut, summary="任务详情（轮询）")
def get_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    job = db.get(VideoGenerationJob, job_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("视频生成任务不存在")
    return job_to_out(job)


@router.post("/tasks/{job_id}/retry", response_model=VideoGenerationJobOut, summary="重试失败任务")
def retry_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
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
    return job_to_out(job)


@router.post("/tasks/{job_id}/regenerate", response_model=VideoGenerationJobOut, status_code=202, summary="基于当前版本重新生成")
def regenerate_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """成功任务也可重新生成；新任务共享 variant_group_id，版本中心可横向比较。"""
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    source = db.get(VideoGenerationJob, job_id)
    if not source or source.project_id != project_id:
        raise NotFoundError("视频生成任务不存在")
    if source.status in ("queued", "running"):
        raise ConflictError("任务正在生成中，请等待完成后再重新生成")
    try:
        job = create_video_job(
            db=db,
            project_id=project_id,
            generation_mode=source.generation_mode,
            first_frame_asset_id=source.first_frame_asset_id or "",
            last_frame_asset_id=source.last_frame_asset_id,
            reference_asset_ids=list(source.reference_asset_ids or []),
            template_id=source.template_id,
            positive_prompt=(source.parameter_snapshot or {}).get("user_prompt", source.positive_prompt or ""),
            negative_prompt=source.negative_prompt,
            duration=source.duration,
            aspect_ratio=source.aspect_ratio,
            resolution=source.resolution,
            seed=source.seed,
            generate_audio=source.generate_audio,
            constraints_enabled=source.constraints_enabled,
            idempotency_key=None,
            created_by=current.username,
            provider=source.provider,
            model_name=source.model_name,
            variant_group_id=source.variant_group_id or source.id,
        )
    except ValueError as exc:
        raise ConflictError(str(exc))
    _dispatch_video_job(db, job)
    db.refresh(job)
    return job_to_out(job)


@router.post("/tasks/{job_id}/cancel", response_model=VideoGenerationJobOut, summary="取消任务")
def cancel_task(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
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
    return job_to_out(job)


@router.get("/tasks/{job_id}/versions", response_model=list[VideoGenerationVersionOut], summary="任务结果版本")
def task_versions(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
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
    return [version_to_out(v) for v in versions]


# ============================================================
# 版本管理
# ============================================================

@router.get("/versions", response_model=list[VideoGenerationVersionOut], summary="项目视频版本列表")
def list_versions(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_VIEW)
    query = db.query(VideoGenerationVersion).filter(VideoGenerationVersion.is_deleted.is_(False))
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
    return [version_to_out(v) for v in versions]


@router.patch("/versions/{version_id}", response_model=VideoGenerationVersionOut, summary="重命名视频版本")
def rename_version(
    project_id: str,
    version_id: str,
    payload: VideoGenerationVersionRenameRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    version = db.get(VideoGenerationVersion, version_id)
    if not version or version.is_deleted:
        raise NotFoundError("视频版本不存在")
    job = db.get(VideoGenerationJob, version.video_job_id)
    if not job or job.project_id != project_id:
        raise NotFoundError("视频版本不存在")
    asset = db.get(Asset, version.result_asset_id) if version.result_asset_id else None
    if not asset or asset.project_id != project_id:
        raise NotFoundError("视频结果素材不存在")
    name = payload.name.strip()
    if not name:
        raise ConflictError("名称不能为空")
    asset.name = name
    db.commit()
    db.refresh(version)
    return version_to_out(version)


@router.post("/versions/{version_id}/select", response_model=VideoGenerationVersionOut, summary="选为当前结果")
def select_result(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    try:
        version = select_version(db, project_id, version_id, current.username)
    except RuntimeError as exc:
        raise ConflictError(str(exc))
    return version_to_out(version)


@router.delete("/versions/{version_id}", status_code=204, summary="删除版本（软删除）")
def delete_version(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current, PERM_MEDIA_EDIT)
    try:
        soft_delete_version(db, project_id, version_id, current.username)
    except RuntimeError as exc:
        raise ConflictError(str(exc))
