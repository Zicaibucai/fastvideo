"""视频工程与导出路由（Phase 5 多分段视频合成）。

保留 Phase 1 旧导出端点；新增分段/预检/演示/正式导出/下载等端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.storage import storage
from app.models.asset import Asset
from app.models.audio_version import AudioVersion
from app.models.export_task import ExportTask
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.user import User
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.schemas.video import (
    ExportRequest,
    ExportStartOut,
    ExportTaskOut,
    PreflightOut,
    SegmentsReorderIn,
    SyncStoryboardOut,
    VideoProjectCreate,
    VideoProjectOut,
    VideoProjectUpdate,
    VideoSegmentOut,
    VideoSegmentPatch,
)
from app.services.task_runner import create_render_task, dispatch
from app.services.video_project_service import (
    VideoProjectError,
    create_export,
    dispatch_export,
    preflight,
    refresh_render_batch_progress,
    render_segment,
    sync_storyboard_to_video_project,
)
from app.tasks.export import export_video_sync, export_video_task
from app.tasks.video_export import render_segment_sync, render_segment_task

router = APIRouter(tags=["视频工程与导出"])


def _get_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def _get_owned_vp(db: Session, vp_id: str, user: User) -> VideoProject:
    vp = db.get(VideoProject, vp_id)
    if not vp:
        raise NotFoundError("视频工程不存在")
    if vp.project_id:
        project = db.get(Project, vp.project_id)
        if not project or project.owner_id != user.id:
            raise NotFoundError("视频工程不存在")
    return vp


def _cancel_previous_segment_tasks(db: Session, segment_id: str) -> None:
    """同一分段重新渲染时，关闭之前遗留的排队/运行任务。"""
    tasks = (
        db.query(RenderTask)
        .filter(
            RenderTask.task_type == "segment_render",
            RenderTask.status.in_(["queued", "running", "retry"]),
        )
        .all()
    )
    changed = False
    for task in tasks:
        if (task.params or {}).get("segment_id") != segment_id:
            continue
        task.status = "cancelled"
        task.progress = 0
        task.error_message = None
        task.message = "已由更新的分段渲染任务替代"
        changed = True
    if changed:
        db.commit()


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


def _audio_version_url(db: Session, version_id: str | None) -> str | None:
    if not version_id:
        return None
    version = db.get(AudioVersion, version_id)
    if not version or version.is_deleted:
        return None
    return _asset_url(db, version.mp3_asset_id or version.audio_asset_id)


def _versioned_file_url(key: str | None, version: str | None = None) -> str | None:
    """为会被覆盖的分段文件追加版本号，避免 video 元素复用旧缓存。"""
    if not key:
        return None
    stamp = "".join(ch for ch in str(version or "") if ch.isalnum())
    return f"/files/{key}?v={stamp}" if stamp else f"/files/{key}"


def _segment_out(db: Session, seg: VideoSegment) -> VideoSegmentOut:
    from app.models.storyboard_shot import StoryboardShot

    shot = db.get(StoryboardShot, seg.storyboard_shot_id) if seg.storyboard_shot_id else None
    visual_asset = db.get(Asset, seg.visual_asset_id) if seg.visual_asset_id else None
    has_visual = bool(visual_asset and visual_asset.asset_type in ("image", "video"))
    audio_version = db.get(AudioVersion, seg.audio_version_id) if seg.audio_version_id else None
    has_audio = bool(audio_version and not audio_version.is_deleted)
    visual_source = "manual" if has_visual else ("placeholder" if shot else "none")
    source_duration = visual_asset.duration_seconds if has_visual else None
    playback_speed = round(source_duration / seg.duration, 4) if source_duration and seg.duration else None
    return VideoSegmentOut(
        id=seg.id,
        video_project_id=seg.video_project_id,
        storyboard_shot_id=seg.storyboard_shot_id,
        sequence=seg.sequence,
        visual_asset_id=seg.visual_asset_id,
        audio_version_id=seg.audio_version_id,
        duration=seg.duration,
        time_adaptation=seg.time_adaptation,
        is_locked=seg.is_locked,
        fit_mode=seg.fit_mode,
        transition_type=seg.transition_type,
        transition_duration=seg.transition_duration,
        subtitle_enabled=seg.subtitle_enabled,
        volume=seg.volume,
        render_status=seg.render_status,
        render_progress=seg.render_progress,
        output_key=seg.output_key,
        output_url=_versioned_file_url(seg.output_key, seg.rendered_at or seg.updated_at),
        input_hash=seg.input_hash,
        needs_rebuild=seg.needs_rebuild,
        error_message=seg.error_message,
        rendered_at=seg.rendered_at,
        created_at=seg.created_at,
        updated_at=seg.updated_at,
        shot_title=shot.title if shot else None,
        narration=shot.narration if shot else None,
        visual_url=_asset_url(db, seg.visual_asset_id) if has_visual else None,
        visual_source_duration=source_duration,
        visual_playback_speed=playback_speed,
        audio_url=_audio_version_url(db, seg.audio_version_id),
        has_visual=has_visual,
        has_audio=has_audio,
        has_subtitle=seg.subtitle_enabled,
        visual_source=visual_source,
    )


def _export_out(db: Session, et: ExportTask) -> ExportTaskOut:
    return ExportTaskOut(
        id=et.id,
        video_project_id=et.video_project_id,
        project_id=et.project_id,
        export_format=et.export_format,
        mode=et.mode,
        status=et.status,
        progress=et.progress,
        attempts=et.attempts,
        output_key=et.output_key,
        output_url=f"/files/{et.output_key}" if et.output_key else None,
        srt_key=et.srt_key,
        srt_url=f"/files/{et.srt_key}" if et.srt_key else None,
        report_key=et.report_key,
        report_url=f"/files/{et.report_key}" if et.report_key else None,
        file_size=et.file_size,
        duration_seconds=et.duration_seconds,
        error_message=et.error_message,
        timeline_snapshot=et.timeline_snapshot,
        created_at=et.created_at,
        updated_at=et.updated_at,
    )


# ============================================================
# 视频工程（保留 + 扩展）
# ============================================================

@router.get("/projects/{project_id}/video-projects", response_model=list[VideoProjectOut], summary="视频工程列表")
def list_video_projects(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[VideoProject]:
    _get_project(db, project_id, current)
    return (
        db.query(VideoProject)
        .filter(VideoProject.project_id == project_id)
        .order_by(VideoProject.created_at.desc())
        .all()
    )


@router.post("/projects/{project_id}/video-projects", response_model=VideoProjectOut, status_code=201, summary="创建视频工程")
def create_video_project(
    project_id: str,
    payload: VideoProjectCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VideoProject:
    _get_project(db, project_id, current)
    data = payload.model_dump(exclude={"project_id"}, exclude_none=True)
    if "fps" in data and data["fps"] not in (24, 25, 30):
        raise ConflictError("fps 仅支持 24/25/30")
    for track in data.get("music_tracks") or []:
        asset = db.get(Asset, track["asset_id"])
        if not asset or asset.project_id != project_id:
            raise NotFoundError("背景音乐素材不存在")
        if asset.asset_type != "audio":
            raise ConflictError("背景音乐只能选择音频素材")
    for item in data.get("timeline") or []:
        if item.get("visual_asset_id"):
            asset = db.get(Asset, item["visual_asset_id"])
            if not asset or asset.project_id != project_id:
                raise NotFoundError("视频素材不存在")
            if asset.asset_type != "video":
                raise ConflictError("视频工程时间轴只能使用视频素材")
    vp = VideoProject(project_id=project_id, **data)
    db.add(vp)
    db.commit()
    db.refresh(vp)
    sync_storyboard_to_video_project(db, vp, current)
    db.refresh(vp)
    return vp


@router.get("/video-projects/{vp_id}", response_model=VideoProjectOut, summary="视频工程详情")
def get_video_project(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VideoProject:
    return _get_owned_vp(db, vp_id, current)


@router.patch("/video-projects/{vp_id}", response_model=VideoProjectOut, summary="更新视频工程")
def update_video_project(
    vp_id: str,
    payload: VideoProjectUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VideoProject:
    vp = _get_owned_vp(db, vp_id, current)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "fps" in data and data["fps"] not in (24, 25, 30):
        raise ConflictError("fps 仅支持 24/25/30")
    if "music_tracks" in data and data["music_tracks"] is not None:
        for track in data["music_tracks"]:
            asset = db.get(Asset, track["asset_id"])
            if not asset or asset.project_id != vp.project_id:
                raise NotFoundError("背景音乐素材不存在")
            if asset.asset_type != "audio":
                raise ConflictError("背景音乐只能选择音频素材")
    if "timeline" in data and data["timeline"] is not None:
        for item in data["timeline"]:
            if item.get("visual_asset_id"):
                asset = db.get(Asset, item["visual_asset_id"])
                if not asset or asset.project_id != vp.project_id:
                    raise NotFoundError("视频素材不存在")
                if asset.asset_type != "video":
                    raise ConflictError("视频工程时间轴只能使用视频素材")
    for field, value in data.items():
        setattr(vp, field, value)
    db.commit()
    db.refresh(vp)
    return vp


@router.delete("/video-projects/{vp_id}", status_code=204, summary="删除视频工程")
def delete_video_project(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    vp = _get_owned_vp(db, vp_id, current)
    db.delete(vp)
    db.commit()


# ============================================================
# 分镜同步 / 分段
# ============================================================

@router.post("/video-projects/{vp_id}/sync-storyboard", response_model=SyncStoryboardOut, summary="同步分镜到分段")
def sync_storyboard(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    vp = _get_owned_vp(db, vp_id, current)
    result = sync_storyboard_to_video_project(db, vp, current)
    segs = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    return SyncStoryboardOut(
        synced=True,
        created=result["created"],
        updated=result["updated"],
        segment_count=result["segment_count"],
        segments=[_segment_out(db, s) for s in segs],
    )


@router.get("/video-projects/{vp_id}/segments", response_model=list[VideoSegmentOut], summary="分段列表")
def list_segments(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[VideoSegmentOut]:
    vp = _get_owned_vp(db, vp_id, current)
    sync_storyboard_to_video_project(db, vp, current)
    segs = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    return [_segment_out(db, s) for s in segs]


@router.patch("/video-projects/{vp_id}/segments/{segment_id}", response_model=VideoSegmentOut, summary="更新分段")
def patch_segment(
    vp_id: str,
    segment_id: str,
    payload: VideoSegmentPatch,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VideoSegmentOut:
    vp = _get_owned_vp(db, vp_id, current)
    seg = db.get(VideoSegment, segment_id)
    if not seg or seg.video_project_id != vp.id:
        raise NotFoundError("分段不存在")
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "visual_asset_id" in data and data["visual_asset_id"]:
        asset = db.get(Asset, data["visual_asset_id"])
        if not asset or asset.project_id != vp.project_id:
            raise NotFoundError("视频素材不存在")
        if asset.asset_type not in ("image", "video"):
            raise ConflictError("视频工程只能选择图片或视频素材")
    if "audio_version_id" in data and data["audio_version_id"]:
        version = db.get(AudioVersion, data["audio_version_id"])
        if not version or version.project_id != vp.project_id or version.is_deleted:
            raise NotFoundError("配音版本不存在")
        if seg.storyboard_shot_id and version.storyboard_shot_id != seg.storyboard_shot_id:
            raise ConflictError("只能选择当前分镜的配音版本")
    for field, value in data.items():
        setattr(seg, field, value)
    rebuild_fields = {
        "duration", "visual_asset_id", "audio_version_id", "time_adaptation", "subtitle_enabled",
        "volume", "fit_mode", "transition_type", "transition_duration",
    }
    if rebuild_fields.intersection(data):
        seg.needs_rebuild = True
        if seg.render_status == "success":
            seg.render_status = "pending"
        # 旧成片不再代表当前设置，避免界面继续播放过期视频。
        seg.output_key = None
        seg.render_progress = 0
        seg.rendered_at = None
    db.commit()
    db.refresh(seg)
    return _segment_out(db, seg)


@router.post("/video-projects/{vp_id}/segments/reorder", response_model=list[VideoSegmentOut], summary="分段排序")
def reorder_segments(
    vp_id: str,
    payload: SegmentsReorderIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[VideoSegmentOut]:
    vp = _get_owned_vp(db, vp_id, current)
    segs = {s.id: s for s in db.query(VideoSegment).filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped").all()}
    for index, sid in enumerate(payload.segment_ids, start=1):
        if sid in segs:
            segs[sid].sequence = index
    db.commit()
    ordered = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    return [_segment_out(db, s) for s in ordered]


def _dispatch_segment_task(db: Session, vp_id: str, seg: VideoSegment, user: User) -> RenderTask:
    vp = db.get(VideoProject, vp_id)
    if not vp:
        raise NotFoundError("视频工程不存在")
    _cancel_previous_segment_tasks(db, seg.id)
    # 先持久化排队状态，Celery 尚未接手时前端也能显示 0% 而不是“待合成”。
    seg.render_status = "queued"
    seg.render_progress = 0
    seg.error_message = None
    db.commit()
    task = create_render_task(
        db,
        project_id=vp.project_id,
        shot_id=seg.storyboard_shot_id,
        task_type="segment_render",
        params={"segment_id": seg.id, "task_id": None},
        message=f"分段#{seg.sequence} 渲染中…",
    )
    task.params = {**(task.params or {}), "task_id": task.id}
    db.commit()
    db.refresh(task)
    dispatch(db, task=task, async_func=render_segment_task, sync_func=render_segment_sync)
    db.refresh(task)
    return task


@router.post("/video-projects/{vp_id}/segments/{segment_id}/render", status_code=202, response_model=dict, summary="渲染单个分段")
def render_single_segment(
    vp_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    vp = _get_owned_vp(db, vp_id, current)
    seg = db.get(VideoSegment, segment_id)
    if not seg or seg.video_project_id != vp.id:
        raise NotFoundError("分段不存在")
    task = _dispatch_segment_task(db, vp_id, seg, current)
    return {"task_id": task.id, "status": task.status, "segment_id": segment_id}


@router.post("/video-projects/{vp_id}/segments/{segment_id}/preview", status_code=202, response_model=dict, summary="预览单个分段")
def preview_single_segment(
    vp_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    vp = _get_owned_vp(db, vp_id, current)
    seg = db.get(VideoSegment, segment_id)
    if not seg or seg.video_project_id != vp.id:
        raise NotFoundError("分段不存在")
    # 已渲染且未失效时直接返回，否则渲染
    if seg.render_status == "success" and seg.output_key and not seg.needs_rebuild:
        return {
            "segment_id": segment_id,
            "status": "success",
            "output_url": _versioned_file_url(seg.output_key, seg.rendered_at or seg.updated_at),
            "cached": True,
        }
    task = _dispatch_segment_task(db, vp_id, seg, current)
    return {"task_id": task.id, "status": task.status, "segment_id": segment_id}


@router.get("/video-projects/{vp_id}/segments/{segment_id}/download", response_model=None, summary="下载已合成分段")
def download_segment(
    vp_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    """下载当前视频工程中已经合成的单个分段。"""
    vp = _get_owned_vp(db, vp_id, current)
    seg = db.get(VideoSegment, segment_id)
    if not seg or seg.video_project_id != vp.id:
        raise NotFoundError("分段不存在")
    if seg.render_status != "success" or not seg.output_key or not storage.exists(seg.output_key):
        raise NotFoundError("该分段尚未完成合成")
    data = storage.load(seg.output_key)
    return _file_response(data, f"segment_{seg.sequence}_{seg.id[:8]}.mp4", "video/mp4")


@router.post("/video-projects/{vp_id}/segments/{segment_id}/retry", status_code=202, response_model=dict, summary="重试失败分段")
def retry_single_segment(
    vp_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    vp = _get_owned_vp(db, vp_id, current)
    seg = db.get(VideoSegment, segment_id)
    if not seg or seg.video_project_id != vp.id:
        raise NotFoundError("分段不存在")
    if seg.render_status in ("running", "queued"):
        raise ConflictError("分段正在渲染中")
    seg.render_status = "pending"
    seg.needs_rebuild = True
    seg.error_message = None
    db.commit()
    task = _dispatch_segment_task(db, vp_id, seg, current)
    return {"task_id": task.id, "status": task.status, "segment_id": segment_id}


@router.post("/video-projects/{vp_id}/segments/render-all", status_code=202, response_model=dict, summary="渲染全部分段")
def render_all_segments(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    vp = _get_owned_vp(db, vp_id, current)
    segs = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    to_render = [s for s in segs if s.render_status != "success" or s.needs_rebuild]
    if not to_render:
        return {"task_id": None, "status": "success", "rendered": 0, "skipped": len(segs)}

    parent = create_render_task(
        db,
        project_id=vp.project_id,
        task_type="segment_render_all",
        params={"video_project_id": vp.id},
        message=f"批量分段渲染中（共 {len(to_render)} 个）…",
    )
    for seg in to_render:
        child = create_render_task(
            db,
            project_id=vp.project_id,
            shot_id=seg.storyboard_shot_id,
            task_type="segment_render",
            params={"segment_id": seg.id, "task_id": None, "parent_task_id": parent.id},
            message=f"分段#{seg.sequence} 渲染中…",
        )
        child.parent_task_id = parent.id
        child.params = {**(child.params or {}), "task_id": child.id, "parent_task_id": parent.id}
        db.commit()
        db.refresh(child)
        dispatch(db, task=child, async_func=render_segment_task, sync_func=render_segment_sync)
    refresh_render_batch_progress(db, parent.id)
    db.refresh(parent)
    return {"task_id": parent.id, "status": parent.status, "rendered": len(to_render), "skipped": len(segs) - len(to_render)}


# ============================================================
# 导出前检查
# ============================================================

@router.post("/video-projects/{vp_id}/preflight", response_model=PreflightOut, summary="导出前检查")
def video_preflight(
    vp_id: str,
    mode: str = Query(default="demo"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    vp = _get_owned_vp(db, vp_id, current)
    if mode not in ("demo", "formal"):
        raise ConflictError("mode 仅支持 demo / formal")
    result = preflight(db, vp, mode)
    return PreflightOut(
        ok=result["ok"],
        mode=result["mode"],
        issues=result["issues"],
        segment_count=result["segment_count"],
        rendered_segment_count=result["rendered_segment_count"],
        missing_render_count=result["missing_render_count"],
    )


# ============================================================
# 导出（Phase 5：demo / formal）
# ============================================================

def _start_export(db: Session, vp: VideoProject, mode: str, user: User) -> ExportStartOut:
    try:
        et = create_export(db, vp, mode, user)
    except VideoProjectError as exc:
        raise ConflictError(exc.message, detail={"issues": exc.issues})
    dispatch_export(db, et)
    db.refresh(et)
    return ExportStartOut(export_task_id=et.id, status=et.status, mode=mode)


@router.post("/video-projects/{vp_id}/export/demo", response_model=ExportStartOut, status_code=202, summary="演示导出")
def export_demo(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ExportStartOut:
    vp = _get_owned_vp(db, vp_id, current)
    return _start_export(db, vp, "demo", current)


@router.post("/video-projects/{vp_id}/export/formal", response_model=ExportStartOut, status_code=202, summary="正式导出")
def export_formal(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ExportStartOut:
    vp = _get_owned_vp(db, vp_id, current)
    return _start_export(db, vp, "formal", current)


@router.get("/video-projects/{vp_id}/exports", response_model=list[ExportTaskOut], summary="导出任务列表")
def list_vp_exports(
    vp_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ExportTaskOut]:
    vp = _get_owned_vp(db, vp_id, current)
    ets = (
        db.query(ExportTask)
        .filter(ExportTask.video_project_id == vp.id)
        .order_by(ExportTask.created_at.desc())
        .limit(50)
        .all()
    )
    return [_export_out(db, et) for et in ets]


@router.get("/exports/{export_id}", response_model=ExportTaskOut, summary="导出任务详情")
def get_export(
    export_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ExportTaskOut:
    et = db.get(ExportTask, export_id)
    if not et:
        raise NotFoundError("导出任务不存在")
    _get_owned_vp(db, et.video_project_id, current)
    return _export_out(db, et)


@router.post("/exports/{export_id}/cancel", response_model=ExportTaskOut, summary="取消导出任务")
def cancel_export(
    export_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ExportTaskOut:
    et = db.get(ExportTask, export_id)
    if not et:
        raise NotFoundError("导出任务不存在")
    _get_owned_vp(db, et.video_project_id, current)
    if et.status in ("queued", "running"):
        et.status = "cancelled"
        db.commit()
    db.refresh(et)
    return _export_out(db, et)


@router.post("/exports/{export_id}/retry", response_model=ExportTaskOut, summary="重试导出任务")
def retry_export(
    export_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ExportTaskOut:
    et = db.get(ExportTask, export_id)
    if not et:
        raise NotFoundError("导出任务不存在")
    vp = _get_owned_vp(db, et.video_project_id, current)
    if et.status not in ("failed", "cancelled"):
        raise ConflictError("仅失败或已取消的导出可重试")
    et.status = "queued"
    et.progress = 0
    et.error_message = None
    db.commit()
    dispatch_export(db, et)
    db.refresh(et)
    return _export_out(db, et)


def _file_response(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/{export_id}/download", response_model=None, summary="下载成片 MP4")
def download_export(
    export_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    et = db.get(ExportTask, export_id)
    if not et:
        raise NotFoundError("导出任务不存在")
    _get_owned_vp(db, et.video_project_id, current)
    if not et.output_key or not storage.exists(et.output_key):
        raise NotFoundError("导出文件不存在")
    data = storage.load(et.output_key)
    return _file_response(data, f"export_{et.id[:8]}.mp4", "video/mp4")


@router.get("/exports/{export_id}/srt", response_model=None, summary="下载独立 SRT")
def download_export_srt(
    export_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    et = db.get(ExportTask, export_id)
    if not et:
        raise NotFoundError("导出任务不存在")
    _get_owned_vp(db, et.video_project_id, current)
    if not et.srt_key or not storage.exists(et.srt_key):
        raise NotFoundError("SRT 文件不存在")
    data = storage.load(et.srt_key)
    return _file_response(data, f"export_{et.id[:8]}.srt", "application/x-subrip; charset=utf-8")


@router.get("/exports/{export_id}/report", response_model=None, summary="下载导出报告")
def download_export_report(
    export_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    et = db.get(ExportTask, export_id)
    if not et:
        raise NotFoundError("导出任务不存在")
    _get_owned_vp(db, et.video_project_id, current)
    if not et.report_key or not storage.exists(et.report_key):
        raise NotFoundError("导出报告不存在")
    data = storage.load(et.report_key)
    return _file_response(data, f"export_{et.id[:8]}_report.json", "application/json")


# ============================================================
# 旧导出端点（Phase 1 兼容，保持原行为）
# ============================================================

@router.post("/video-projects/{vp_id}/export", status_code=202, summary="发起视频导出（兼容）")
def start_export(
    vp_id: str,
    payload: ExportRequest | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    vp = _get_owned_vp(db, vp_id, current)

    export_task = ExportTask(
        video_project_id=vp_id,
        project_id=vp.project_id,
        export_format=payload.export_format if payload else "mp4",
        mode="demo",
        status="queued",
        progress=0,
        params={"video_project_id": vp_id, "export_format": payload.export_format if payload else "mp4"},
    )
    db.add(export_task)
    db.commit()
    db.refresh(export_task)

    render_task = create_render_task(
        db,
        project_id=vp.project_id,
        task_type="export",
        params={"video_project_id": vp_id, "export_format": export_task.export_format},
        message="导出视频中…",
    )
    vp.status = "composing"
    db.commit()

    dispatch(db, task=render_task, async_func=export_video_task, sync_func=export_video_sync)

    export_task.result = render_task.result
    if render_task.status == "success" and render_task.result:
        export_task.status = "success"
        export_task.output_key = render_task.result.get("output_key")
        export_task.output_url = (
            storage.url(render_task.result["output_key"]) if render_task.result.get("output_key") else None
        )
        db.commit()
    elif render_task.status == "failed":
        export_task.status = "failed"
        export_task.error_message = render_task.error_message
        db.commit()

    return {"export_task_id": export_task.id, "render_task_id": render_task.id, "status": export_task.status}


@router.get("/exports", response_model=list[ExportTaskOut], summary="导出任务列表（全局）")
def list_exports(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ExportTaskOut]:
    query = db.query(ExportTask)
    if project_id:
        query = query.filter(ExportTask.project_id == project_id)
    ets = query.order_by(ExportTask.created_at.desc()).limit(100).all()
    return [_export_out(db, et) for et in ets]
