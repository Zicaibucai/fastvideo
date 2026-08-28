"""AI 视频路由的共享校验与响应映射。

路由文件只负责 HTTP 编排；数据库模型到 API schema 的映射集中放在这里，
避免模板、任务和版本路由分别维护一套容易漂移的字段转换逻辑。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.asset import Asset
from app.models.project import Project
from app.models.user import User
from app.models.video_generation import VideoGenerationJob, VideoGenerationTemplate, VideoGenerationVersion, VideoTemplateDraft
from app.schemas.video_gen import VideoGenerationJobOut, VideoGenerationTemplateOut, VideoGenerationVersionOut, VideoTemplateDraftOut


def prompt_master_mock_allowed() -> bool:
    """读取启动配置，并兼容测试/本地演示在导入后设置的环境变量。"""
    if settings.ai_prompt_master_allow_mock:
        return True
    return os.getenv('AI_PROMPT_MASTER_ALLOW_MOCK', '').strip().lower() in {'1', 'true', 'yes', 'on'}


def get_owned_project(db: Session, project_id: str, user: User, permission: str = 'project.view') -> Project:
    from app.services.permissions import get_project_access

    return get_project_access(db, project_id, user, permission).project


def job_to_out(job: VideoGenerationJob) -> VideoGenerationJobOut:
    result_url = None
    if job.result_asset_id and job.result_asset and job.result_asset.file_key:
        result_url = f'/files/{job.result_asset.file_key}'
    return VideoGenerationJobOut(
        id=job.id,
        project_id=job.project_id,
        generation_mode=job.generation_mode,
        first_frame_asset_id=job.first_frame_asset_id,
        last_frame_asset_id=job.last_frame_asset_id,
        reference_asset_ids=list(job.reference_asset_ids or []),
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
        asset_status='ready' if job.result_asset_id else 'failed' if job.status == 'failed' else 'processing',
        result_url=result_url,
        quality_report=(job.result_asset.meta or {}).get('quality_report') if job.result_asset else None,
        parameter_snapshot=job.parameter_snapshot,
        created_by=job.created_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at.isoformat() if job.created_at else None,
        version_count=len(job.versions),
    )


def version_to_out(version: VideoGenerationVersion) -> VideoGenerationVersionOut:
    result_url = None
    if version.result_asset_id and version.result_asset and version.result_asset.file_key:
        result_url = f'/files/{version.result_asset.file_key}'
    return VideoGenerationVersionOut(
        id=version.id,
        video_job_id=version.video_job_id,
        result_asset_id=version.result_asset_id,
        name=version.result_asset.name if version.result_asset else None,
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
        reference_asset_ids=list(version.reference_asset_ids or []),
        quality_report=(version.result_asset.meta or {}).get('quality_report') if version.result_asset else None,
        template_id=version.template_id,
        is_selected=version.is_selected,
        selected_by=version.selected_by,
        selected_at=version.selected_at,
        is_deleted=version.is_deleted,
        created_at=version.created_at.isoformat() if version.created_at else None,
    )


def template_to_out(template: VideoGenerationTemplate) -> VideoGenerationTemplateOut:
    return VideoGenerationTemplateOut(
        id=template.id,
        name=template.name,
        description=template.description,
        applicable_modes=template.applicable_modes,
        default_positive_prompt=template.default_positive_prompt,
        default_negative_prompt=template.default_negative_prompt,
        recommended_duration=template.recommended_duration,
        recommended_aspect_ratio=template.recommended_aspect_ratio,
        recommended_resolution=template.recommended_resolution,
        recommended_camera_motion=template.recommended_camera_motion,
        default_arch_constraints=template.default_arch_constraints,
        is_system=template.is_system,
        is_enabled=template.is_enabled,
        created_by=template.created_by,
        sort_order=template.sort_order,
        source_template_id=template.source_template_id,
        category=template.category,
        tags=template.tags,
        prompt_recipe=template.prompt_recipe,
        preview_asset_id=template.preview_asset_id,
        cover_asset_id=template.cover_asset_id,
        preview_file_key=template.preview_asset.file_key if template.preview_asset else None,
        cover_file_key=template.cover_asset.file_key if template.cover_asset else None,
        scope=template.scope,
        status=template.status,
        source_video_asset_id=template.source_video_asset_id,
        clip_start_seconds=template.clip_start_seconds,
        clip_end_seconds=template.clip_end_seconds,
        first_frame_asset_id=template.first_frame_asset_id,
        middle_frame_asset_id=template.middle_frame_asset_id,
        last_frame_asset_id=template.last_frame_asset_id,
        first_frame_file_key=template.first_frame_asset.file_key if template.first_frame_asset else None,
        middle_frame_file_key=template.middle_frame_asset.file_key if template.middle_frame_asset else None,
        last_frame_file_key=template.last_frame_asset.file_key if template.last_frame_asset else None,
        reference_frame_asset_ids=list(template.reference_frame_asset_ids or []),
        reference_frame_times=[float(value) for value in (template.reference_frame_times or [])],
        reference_frame_count=template.reference_frame_count,
        source_license_confirmed=template.source_license_confirmed,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def draft_to_out(db: Session, draft: VideoTemplateDraft) -> VideoTemplateDraftOut:
    source, first, middle, last, preview = draft.source_video_asset, draft.first_frame_asset, draft.middle_frame_asset, draft.last_frame_asset, draft.preview_asset
    reference_assets = [db.get(Asset, asset_id) for asset_id in (draft.reference_frame_asset_ids or [])]
    return VideoTemplateDraftOut(
        id=draft.id,
        project_id=draft.project_id,
        source_video_asset_id=draft.source_video_asset_id,
        source_video_name=source.name if source else None,
        source_video_file_key=source.file_key if source else None,
        source_video_duration_seconds=source.duration_seconds if source else None,
        name=draft.name,
        description=draft.description,
        status=draft.status,
        clip_start_seconds=draft.clip_start_seconds,
        clip_end_seconds=draft.clip_end_seconds,
        middle_seconds=draft.middle_seconds,
        first_frame_asset_id=draft.first_frame_asset_id,
        middle_frame_asset_id=draft.middle_frame_asset_id,
        last_frame_asset_id=draft.last_frame_asset_id,
        first_frame_file_key=first.file_key if first else None,
        middle_frame_file_key=middle.file_key if middle else None,
        last_frame_file_key=last.file_key if last else None,
        reference_frame_asset_ids=list(draft.reference_frame_asset_ids or []),
        reference_frame_times=[float(value) for value in (draft.reference_frame_times or [])],
        reference_frame_file_keys=[asset.file_key for asset in reference_assets if asset and asset.file_key],
        prompt_recipe=draft.prompt_recipe,
        analysis_warnings=draft.analysis_warnings,
        intent=draft.intent,
        preview_job_id=draft.preview_job_id,
        preview_asset_id=draft.preview_asset_id,
        preview_file_key=preview.file_key if preview else None,
        template_id=draft.template_id,
        source_license_confirmed=draft.source_license_confirmed,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
