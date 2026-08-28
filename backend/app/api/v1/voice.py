"""Phase 4 配音 API 路由。

三个路由器：
- pronunciation_router：/projects/{project_id}/pronunciations 发音词典
- voice_router：/projects/{project_id}/voice 估算/生成/批量/任务/导出/汇总
- shot_voice_router：/projects/{project_id}/storyboard/{shot_id}/voice/... 版本与字幕
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.adapters.factory import get_tts_adapter, tts_provider_info
from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.permissions import (
    get_project_access,
    PERM_MEDIA_EDIT,
    PERM_MEDIA_VIEW,
    PERM_VOICE_EDIT,
    PERM_VOICE_VIEW,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.core.storage import storage
from app.models.asset import Asset
from app.models.audio_version import AudioVersion
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.models.voice_template import VoiceTemplate
from app.schemas.voice import (
    PronunciationImportIn,
    PronunciationRuleCreate,
    PronunciationRuleOut,
    PronunciationRuleUpdate,
    PronunciationTestIn,
    PronunciationTestOut,
    SubtitleUpdateRequest,
    VoiceBatchRequest,
    VoiceEstimateRequest,
    VoiceGenerateRequest,
    VoiceRestoreRequest,
    VoiceSelectRequest,
)
from app.services.audit import log_action
from app.services.pronunciation_service import (
    create_rule,
    delete_rule,
    detect_conflicts,
    export_rules_json,
    get_effective_rules,
    import_rules_json,
    list_rules,
    test_read,
    update_rule,
    validate_regex,
)
from app.services.task_runner import create_render_task, dispatch
from app.services.voice_service import (
    VoiceError,
    estimate_for_shot,
    export_project_srt,
    export_voice_audio_zip,
    generate_voice_version,
    list_versions_for_shot,
    prepare_shot_list_for_batch,
    project_voice_summary,
    refresh_batch_progress,
    restore_voice_version,
    select_voice_version,
    soft_delete_voice_version,
)
from app.tasks.voice import gen_voice_version_sync, gen_voice_version_task

pronunciation_router = APIRouter(prefix="/projects/{project_id}/pronunciations", tags=["发音词典"])
voice_router = APIRouter(prefix="/projects/{project_id}/voice", tags=["配音制作"])
shot_voice_router = APIRouter(prefix="/projects/{project_id}/storyboard", tags=["分镜配音"])

_ALL_TTS_CAP_KEYS = [
    "synthesize", "ssml", "timestamps", "word_timestamps", "sentence_timestamps",
    "speed_control", "pitch_control", "volume_control", "emotion", "streaming",
    "voice_preview", "mp3", "wav", "voice_cloning",
]


def _get_project(db: Session, project_id: str, user: User, permission: str = PERM_VOICE_VIEW) -> Project:
    """统一项目访问：成员校验 + 细粒度权限（非成员 404，权限不足 403）。"""
    return get_project_access(db, project_id, user, permission).project


def _get_shot(db: Session, project_id: str, shot_id: str) -> StoryboardShot:
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")
    return shot


def _asset_url(db: Session, asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    asset = db.get(Asset, asset_id)
    if not asset:
        return None
    if asset.url:
        return asset.url
    if asset.file_key:
        return f"/files/{asset.file_key}"
    return None


def _version_out(db: Session, v: AudioVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "project_id": v.project_id,
        "storyboard_shot_id": v.storyboard_shot_id,
        "voice_template_id": v.voice_template_id,
        "version_number": v.version_number,
        "original_text_snapshot": v.original_text_snapshot,
        "normalized_text_snapshot": v.normalized_text_snapshot,
        "pronunciation_snapshot": v.pronunciation_snapshot,
        "narration_hash": v.narration_hash,
        "provider": v.provider,
        "model_name": v.model_name,
        "voice_id": v.voice_id,
        "speed": v.speed,
        "pitch": v.pitch,
        "volume": v.volume,
        "emotion": v.emotion,
        "pause_strength": v.pause_strength,
        "seed": v.seed,
        "target_duration_seconds": v.target_duration_seconds,
        "estimated_duration_seconds": v.estimated_duration_seconds,
        "actual_duration_seconds": v.actual_duration_seconds,
        "duration_difference": v.duration_difference,
        "duration_difference_ratio": v.duration_difference_ratio,
        "duration_status": v.duration_status,
        "audio_asset_id": v.audio_asset_id,
        "wav_asset_id": v.wav_asset_id,
        "mp3_asset_id": v.mp3_asset_id,
        "audio_url": _asset_url(db, v.mp3_asset_id or v.audio_asset_id),
        "wav_url": _asset_url(db, v.wav_asset_id),
        "mp3_url": _asset_url(db, v.mp3_asset_id),
        "subtitle_data": v.subtitle_data or [],
        "waveform_data": v.waveform_data,
        "provider_metadata": v.provider_metadata,
        "quality_metrics": v.quality_metrics,
        "quality_status": v.quality_status,
        "authorization_snapshot": v.authorization_snapshot,
        "is_mock": v.is_mock,
        "is_stale": v.is_stale,
        "stale_reason": v.stale_reason,
        "is_selected": v.is_selected,
        "selected_by": v.selected_by,
        "selected_at": v.selected_at,
        "estimated_cost": v.estimated_cost,
        "actual_cost": v.actual_cost,
        "currency": v.currency,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


def _task_out(t: RenderTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "project_id": t.project_id,
        "shot_id": t.shot_id,
        "parent_task_id": t.parent_task_id,
        "task_type": t.task_type,
        "status": t.status,
        "progress": t.progress,
        "params": t.params,
        "result": t.result,
        "error_message": t.error_message,
        "message": t.message,
        "attempts": t.attempts,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


# ============================================================
# Provider 能力
# ============================================================

@voice_router.get("/providers", response_model=list, summary="TTS Provider 列表")
def voice_providers(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    return tts_provider_info()


@voice_router.get("/providers/{provider}/capabilities", response_model=dict, summary="Provider 能力")
def voice_provider_capabilities(
    project_id: str,
    provider: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    adapter = get_tts_adapter()
    if provider in ("mock", "disabled", adapter.provider):
        return adapter.capabilities()
    return {cap: False for cap in _ALL_TTS_CAP_KEYS}


@voice_router.get("/providers/{provider}/voices", response_model=list, summary="音色列表")
def voice_provider_voices(
    project_id: str,
    provider: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    adapter = get_tts_adapter()
    if provider in ("mock", "disabled", adapter.provider):
        return adapter.list_voices()
    return []


# ============================================================
# 发音词典
# ============================================================

@pronunciation_router.get("", response_model=list[PronunciationRuleOut], summary="发音词典规则列表")
def list_pronunciations(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    return list_rules(db, project_id)


@pronunciation_router.post("", response_model=PronunciationRuleOut, status_code=201, summary="创建发音规则")
def create_pronunciation(
    project_id: str,
    payload: PronunciationRuleCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    if payload.is_regex:
        validate_regex(payload.source_text)
    conflicts = detect_conflicts(db, project_id, payload.source_text)
    try:
        rule = create_rule(
            db,
            project_id=project_id,
            source_text=payload.source_text,
            spoken_text=payload.spoken_text,
            rule_type=payload.rule_type,
            priority=payload.priority,
            is_regex=payload.is_regex,
            scope=payload.scope,
            created_by=current.username,
            is_superuser=current.is_superuser,
        )
    except ConflictError as exc:
        raise ConflictError(str(exc))
    if conflicts:
        rule.conflict_hint = "与更高优先级规则存在冲突：" + "、".join(
            f"{c['source_text']}→{c['spoken_text']}" for c in conflicts[:5]
        )
        db.commit()
    log_action(db, user=current, project_id=project_id, action="pronunciation_create",
               entity_type="pronunciation_rule", entity_id=rule.id, commit=True)
    return rule


@pronunciation_router.patch("/{rule_id}", response_model=PronunciationRuleOut, summary="更新发音规则")
def patch_pronunciation(
    project_id: str,
    rule_id: str,
    payload: PronunciationRuleUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    try:
        return update_rule(db, rule_id, payload.model_dump(exclude_unset=True), is_superuser=current.is_superuser)
    except ConflictError as exc:
        raise ConflictError(str(exc))


@pronunciation_router.delete("/{rule_id}", status_code=204, summary="删除发音规则")
def remove_pronunciation(
    project_id: str,
    rule_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    try:
        delete_rule(db, rule_id, is_superuser=current.is_superuser)
    except ConflictError as exc:
        raise ConflictError(str(exc))


@pronunciation_router.post("/test", response_model=PronunciationTestOut, summary="测试朗读文本")
def test_pronunciation(
    project_id: str,
    payload: PronunciationTestIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    return test_read(db, project_id, payload.text)


@pronunciation_router.post("/import", response_model=dict, summary="导入发音词典 JSON")
def import_pronunciations(
    project_id: str,
    payload: PronunciationImportIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    result = import_rules_json(
        db,
        project_id,
        {"rules": payload.rules},
        created_by=current.username,
        is_superuser=current.is_superuser,
    )
    log_action(db, user=current, project_id=project_id, action="pronunciation_import",
               entity_type="pronunciation_profile", detail=result, commit=True)
    return result


@pronunciation_router.get("/export", response_model=dict, summary="导出发音词典 JSON")
def export_pronunciations(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    return export_rules_json(db, project_id)


# ============================================================
# 估算 / 生成 / 批量
# ============================================================

@voice_router.post("/estimate", response_model=dict, summary="配音前时长估算")
def voice_estimate(
    project_id: str,
    payload: VoiceEstimateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    _get_shot(db, project_id, payload.shot_id)
    try:
        return estimate_for_shot(db, project_id, payload.shot_id, payload.voice_template_id)
    except VoiceError as exc:
        raise ConflictError(exc.message)


@voice_router.post("/generate", status_code=202, summary="生成单条分镜配音")
def voice_generate(
    project_id: str,
    payload: VoiceGenerateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    shot = _get_shot(db, project_id, payload.shot_id)
    if not (shot.narration or "").strip():
        raise ConflictError("分镜解说词为空，无法生成配音。")

    task = create_render_task(
        db,
        project_id=project_id,
        shot_id=payload.shot_id,
        task_type="gen_voice_version",
        params={
            "project_id": project_id,
            "shot_id": payload.shot_id,
            "voice_template_id": payload.voice_template_id,
            "user_name": current.username,
            "speed": payload.speed,
            "pitch": payload.pitch,
            "volume": payload.volume,
            "emotion": payload.emotion,
            "pause_strength": payload.pause_strength,
            "normalized_text_override": payload.normalized_text_override,
            "seed": payload.seed,
            "output_formats": payload.output_formats or ["wav", "mp3"],
            "idempotency_key": payload.idempotency_key,
        },
        message="AI 配音生成中…",
    )
    # 幂等键去重
    if payload.idempotency_key:
        dup = _find_task_by_idempotency(db, project_id, payload.idempotency_key, task.id)
        if dup:
            return {"task_id": dup.id, "status": dup.status, "duplicate": True}

    dispatch(db, task=task, async_func=gen_voice_version_task, sync_func=gen_voice_version_sync)
    db.refresh(task)
    log_action(db, user=current, project_id=project_id, action="voice_generate",
               entity_type="storyboard_shot", entity_id=payload.shot_id,
               detail={"task_id": task.id, "voice_template_id": payload.voice_template_id}, commit=True)
    return {"task_id": task.id, "status": task.status}


def _find_task_by_idempotency(db: Session, project_id: str, key: str, exclude_id: str | None = None) -> RenderTask | None:
    tasks = (
        db.query(RenderTask)
        .filter(RenderTask.project_id == project_id, RenderTask.task_type == "gen_voice_version")
        .order_by(RenderTask.created_at.desc())
        .all()
    )
    for t in tasks:
        if t.id == exclude_id:
            continue
        params = t.params or {}
        if params.get("idempotency_key") == key:
            return t
    return None


@voice_router.post("/batch", status_code=202, summary="批量生成配音（父任务+子任务）")
def voice_batch(
    project_id: str,
    payload: VoiceBatchRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)

    # 幂等键
    if payload.idempotency_key:
        existing = (
            db.query(RenderTask)
            .filter(
                RenderTask.project_id == project_id,
                RenderTask.task_type == "tts_batch",
            )
            .order_by(RenderTask.created_at.desc())
            .all()
        )
        for t in existing:
            params = t.params or {}
            if params.get("idempotency_key") == payload.idempotency_key:
                refresh_batch_progress(db, t.id)
                return {"task_id": t.id, "status": t.status, "duplicate": True}

    shots = prepare_shot_list_for_batch(
        db,
        project_id,
        payload.shot_ids,
        skip_empty=payload.skip_empty,
        regenerate_stale=payload.regenerate_stale,
    )
    if not shots:
        raise ConflictError("没有需要生成配音的分镜（可能已全部完成或解说词为空）。")
    if len(shots) > 200:
        raise ConflictError("单次批量最多 200 个分镜。")

    parent = create_render_task(
        db,
        project_id=project_id,
        task_type="tts_batch",
        params={
            "voice_template_id": payload.voice_template_id,
            "skip_empty": payload.skip_empty,
            "regenerate_stale": payload.regenerate_stale,
            "idempotency_key": payload.idempotency_key,
            "duration_strategy": payload.duration_strategy,
            "shot_ids": [s.id for s in shots],
        },
        message=f"批量配音生成中（共 {len(shots)} 个分镜）…",
    )

    for shot in shots:
        child = create_render_task(
            db,
            project_id=project_id,
            shot_id=shot.id,
            task_type="gen_voice_version",
            params={
                "project_id": project_id,
                "shot_id": shot.id,
                "voice_template_id": payload.voice_template_id,
                "user_name": current.username,
                "speed": payload.speed,
                "pause_strength": payload.pause_strength,
                "output_formats": payload.output_formats or ["wav", "mp3"],
                "parent_task_id": parent.id,
                "task_id": None,  # 由 dispatch 分发后回填
            },
            message=f"分镜{shot.sequence} 配音生成中…",
        )
        child.parent_task_id = parent.id
        child.params = {
            **(child.params or {}),
            "task_id": child.id,
            "parent_task_id": parent.id,
        }
        db.commit()
        db.refresh(child)
        dispatch(db, task=child, async_func=gen_voice_version_task, sync_func=gen_voice_version_sync)

    refresh_batch_progress(db, parent.id)
    log_action(db, user=current, project_id=project_id, action="voice_batch",
               entity_type="render_task", entity_id=parent.id,
               detail={"shot_count": len(shots)}, commit=True)
    return {"task_id": parent.id, "status": parent.status, "total": len(shots)}


# ============================================================
# 任务
# ============================================================

@voice_router.get("/jobs", response_model=list, summary="配音任务列表")
def voice_jobs(
    project_id: str,
    status: str | None = None,
    shot_id: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    query = db.query(RenderTask).filter(
        RenderTask.project_id == project_id,
        RenderTask.task_type.in_(["gen_voice_version", "tts_batch"]),
    )
    if status:
        query = query.filter(RenderTask.status == status)
    if shot_id:
        query = query.filter(RenderTask.shot_id == shot_id)
    tasks = query.order_by(RenderTask.created_at.desc()).limit(200).all()
    return [_task_out(t) for t in tasks]


@voice_router.get("/jobs/{job_id}", response_model=dict, summary="配音任务详情（轮询）")
def voice_job_detail(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    task = db.get(RenderTask, job_id)
    if not task or task.project_id != project_id:
        raise NotFoundError("任务不存在")
    if task.task_type == "tts_batch":
        refresh_batch_progress(db, task.id)
        db.refresh(task)
    out = _task_out(task)
    if task.task_type == "tts_batch":
        children = (
            db.query(RenderTask)
            .filter(RenderTask.parent_task_id == task.id)
            .order_by(RenderTask.created_at.asc())
            .all()
        )
        out["children"] = [_task_out(c) for c in children]
    return out


@voice_router.post("/jobs/{job_id}/retry", response_model=dict, summary="重试失败任务")
def voice_job_retry(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    task = db.get(RenderTask, job_id)
    if not task or task.project_id != project_id:
        raise NotFoundError("任务不存在")
    if task.status not in ("failed", "cancelled"):
        raise ConflictError("仅失败或已取消的任务可重试")
    task.status = "queued"
    task.progress = 0
    task.error_message = None
    task.attempts = 0
    db.commit()
    dispatch(db, task=task, async_func=gen_voice_version_task, sync_func=gen_voice_version_sync)
    db.refresh(task)
    return _task_out(task)


@voice_router.post("/jobs/{job_id}/cancel", response_model=dict, summary="取消任务")
def voice_job_cancel(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    task = db.get(RenderTask, job_id)
    if not task or task.project_id != project_id:
        raise NotFoundError("任务不存在")
    # 批量任务：取消所有未开始/进行中的子任务
    if task.task_type == "tts_batch":
        children = db.query(RenderTask).filter(RenderTask.parent_task_id == task.id).all()
        for c in children:
            if c.status in ("queued", "running"):
                c.status = "cancelled"
        refresh_batch_progress(db, task.id)
    elif task.status in ("queued", "running"):
        task.status = "cancelled"
        db.commit()
    db.refresh(task)
    return _task_out(task)


# ============================================================
# 版本管理
# ============================================================

@shot_voice_router.get("/{shot_id}/voice/versions", response_model=list, summary="分镜配音版本列表")
def shot_voice_versions(
    project_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    _get_shot(db, project_id, shot_id)
    versions = list_versions_for_shot(db, project_id, shot_id)
    return [_version_out(db, v) for v in versions]


@shot_voice_router.get("/{shot_id}/voice/versions/{version_id}", response_model=dict, summary="配音版本详情")
def shot_voice_version_detail(
    project_id: str,
    shot_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    v = db.get(AudioVersion, version_id)
    if not v or v.project_id != project_id or v.storyboard_shot_id != shot_id or v.is_deleted:
        raise NotFoundError("配音版本不存在")
    return _version_out(db, v)


@shot_voice_router.post("/{shot_id}/voice/versions/{version_id}/select", response_model=dict, summary="设为正式配音")
def shot_voice_select(
    project_id: str,
    shot_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    try:
        result = select_voice_version(db, project_id, shot_id, version_id, current.username)
    except VoiceError as exc:
        raise ConflictError(exc.message)
    log_action(db, user=current, project_id=project_id, action="voice_select",
               entity_type="audio_version", entity_id=version_id, commit=True)
    return result


@shot_voice_router.post("/{shot_id}/voice/restore", response_model=dict, summary="恢复历史正式配音")
def shot_voice_restore(
    project_id: str,
    shot_id: str,
    payload: VoiceRestoreRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    try:
        result = restore_voice_version(db, project_id, shot_id, payload.version_id, current.username)
    except VoiceError as exc:
        raise ConflictError(exc.message)
    log_action(db, user=current, project_id=project_id, action="voice_restore",
               entity_type="audio_version", entity_id=payload.version_id, commit=True)
    return result


@shot_voice_router.delete("/{shot_id}/voice/versions/{version_id}", status_code=204, summary="删除配音版本（软删除）")
def shot_voice_delete(
    project_id: str,
    shot_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    try:
        soft_delete_voice_version(db, project_id, shot_id, version_id, current.username)
    except VoiceError as exc:
        raise ConflictError(exc.message)
    log_action(db, user=current, project_id=project_id, action="voice_version_delete",
               entity_type="audio_version", entity_id=version_id, commit=True)


# ============================================================
# 字幕
# ============================================================

def _target_version(db: Session, project_id: str, shot_id: str, version_id: str | None) -> AudioVersion:
    if version_id:
        v = db.get(AudioVersion, version_id)
        if not v or v.project_id != project_id or v.storyboard_shot_id != shot_id or v.is_deleted:
            raise NotFoundError("配音版本不存在")
        return v
    v = (
        db.query(AudioVersion)
        .filter(
            AudioVersion.storyboard_shot_id == shot_id,
            AudioVersion.project_id == project_id,
            AudioVersion.is_selected.is_(True),
            AudioVersion.is_deleted.is_(False),
        )
        .first()
    )
    if not v:
        raise NotFoundError("该分镜暂无正式配音版本")
    return v


@shot_voice_router.get("/{shot_id}/subtitles", response_model=dict, summary="分镜字幕句段")
def shot_subtitles(
    project_id: str,
    shot_id: str,
    version_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    _get_shot(db, project_id, shot_id)
    v = _target_version(db, project_id, shot_id, version_id)
    return {
        "shot_id": shot_id,
        "version_id": v.id,
        "version_number": v.version_number,
        "subtitle_data": v.subtitle_data or [],
        "audio_url": _asset_url(db, v.mp3_asset_id or v.audio_asset_id),
        "duration_seconds": v.actual_duration_seconds,
    }


@shot_voice_router.patch("/{shot_id}/subtitles", response_model=dict, summary="修改字幕时间轴")
def patch_shot_subtitles(
    project_id: str,
    shot_id: str,
    payload: SubtitleUpdateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    _get_shot(db, project_id, shot_id)
    v = _target_version(db, project_id, shot_id, None)
    segments = v.subtitle_data or []
    by_seq = {s.get("sequence"): s for s in segments}
    duration_ms = int((v.actual_duration_seconds or 0) * 1000)

    for seg in payload.segments:
        if seg.end_ms <= seg.start_ms:
            raise ConflictError(f"字幕 {seg.sequence} 结束时间必须大于开始时间")
        if seg.end_ms > duration_ms + 100:
            raise ConflictError(f"字幕 {seg.sequence} 结束时间不能超过音频时长")
        target = by_seq.get(seg.sequence)
        if target is None:
            raise NotFoundError(f"字幕 {seg.sequence} 不存在")
        target["start_ms"] = seg.start_ms
        target["end_ms"] = seg.end_ms
        target["timing_source"] = "manual"
        target["confidence"] = 1.0

    # 防止重叠（按开始时间排序后校验）
    ordered = sorted(segments, key=lambda s: s.get("start_ms", 0))
    for i in range(len(ordered) - 1):
        if ordered[i + 1]["start_ms"] < ordered[i]["end_ms"]:
            raise ConflictError("字幕时间轴重叠，请检查后重试")
    if ordered:
        if ordered[0]["start_ms"] < 0:
            raise ConflictError("字幕开始时间不能小于 0")
        if ordered[-1]["end_ms"] > duration_ms:
            raise ConflictError("字幕结束时间不能超过音频时长")

    # 重新编号
    for idx, seg in enumerate(ordered, start=1):
        seg["sequence"] = idx
    v.subtitle_data = ordered
    db.commit()
    log_action(db, user=current, project_id=project_id, action="subtitle_edit",
               entity_type="audio_version", entity_id=v.id, commit=True)
    return {"shot_id": shot_id, "version_id": v.id, "subtitle_data": v.subtitle_data}


@shot_voice_router.get("/{shot_id}/subtitles/export", response_model=None, summary="导出单条分镜 SRT")
def shot_subtitles_export(
    project_id: str,
    shot_id: str,
    version_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    v = _target_version(db, project_id, shot_id, version_id)
    from app.services.audio_utils import render_srt

    content = render_srt(v.subtitle_data or []).encode("utf-8")
    shot = _get_shot(db, project_id, shot_id)
    filename = f"shot{shot.sequence}_{shot.id[:8]}.srt"
    return Response(
        content=content,
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# 导出 / 汇总
# ============================================================

@voice_router.get("/export/srt", response_model=None, summary="导出项目级 SRT")
def export_project_srt_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    content = export_project_srt(db, project_id)
    return Response(
        content=content,
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="project_subtitles.srt"'},
    )


@voice_router.get("/export/wav", response_model=None, summary="导出全部正式配音 WAV（zip）")
def export_voice_wav(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    data, filename = export_voice_audio_zip(db, project_id, fmt="wav")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@voice_router.get("/export/mp3", response_model=None, summary="导出全部正式配音 MP3（zip）")
def export_voice_mp3(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    data, filename = export_voice_audio_zip(db, project_id, fmt="mp3")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@voice_router.get("/summary", response_model=dict, summary="项目配音汇总")
def voice_summary(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    return project_voice_summary(db, project_id)
