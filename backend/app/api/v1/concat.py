"""分镜拼接路由：直接选择多个视频素材按顺序拼接导出，独立于视频工程。

任务记录复用 ExportTask（mode="concat"、video_project_id=None），
因此不挂在现有 /exports 端点下（那里的权限校验假定视频工程存在）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.storage import storage
from app.models.export_task import ExportTask
from app.models.project import Project
from app.models.user import User
from app.schemas.video import ConcatCreateIn, ConcatTaskOut
from app.services.permissions import get_project_access, PERM_VIDEO_EDIT, PERM_VIDEO_VIEW
from app.services.video_concat_service import (
    VideoProjectError,
    create_concat_task,
    dispatch_concat,
)

router = APIRouter(tags=["分镜拼接"])


def _get_project(db: Session, project_id: str, user: User, permission: str) -> Project:
    return get_project_access(db, project_id, user, permission).project


def _get_concat_task(db: Session, task_id: str, user: User, permission: str) -> ExportTask:
    et = db.get(ExportTask, task_id)
    if not et or et.mode != "concat" or not et.project_id:
        raise NotFoundError("拼接任务不存在")
    try:
        get_project_access(db, et.project_id, user, permission)
    except NotFoundError:
        raise NotFoundError("拼接任务不存在") from None
    return et


def _concat_out(et: ExportTask) -> ConcatTaskOut:
    return ConcatTaskOut(
        id=et.id,
        project_id=et.project_id,
        status=et.status,
        progress=et.progress,
        output_key=et.output_key,
        output_url=f"/files/{et.output_key}" if et.output_key else None,
        file_size=et.file_size,
        duration_seconds=et.duration_seconds,
        error_message=et.error_message,
        params=et.params,
        created_at=et.created_at,
        updated_at=et.updated_at,
    )


@router.post("/projects/{project_id}/video-concats", response_model=ConcatTaskOut, status_code=202, summary="创建分镜拼接任务")
def create_concat(
    project_id: str,
    payload: ConcatCreateIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ConcatTaskOut:
    project = _get_project(db, project_id, current, PERM_VIDEO_EDIT)
    try:
        et = create_concat_task(db, project, payload, current)
    except VideoProjectError as exc:
        raise ConflictError(exc.message) from None
    dispatch_concat(db, et)
    db.refresh(et)
    return _concat_out(et)


@router.get("/projects/{project_id}/video-concats", response_model=list[ConcatTaskOut], summary="分镜拼接任务列表")
def list_concats(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ConcatTaskOut]:
    _get_project(db, project_id, current, PERM_VIDEO_VIEW)
    ets = (
        db.query(ExportTask)
        .filter(ExportTask.project_id == project_id, ExportTask.mode == "concat")
        .order_by(ExportTask.created_at.desc())
        .limit(50)
        .all()
    )
    return [_concat_out(et) for et in ets]


@router.get("/video-concats/{task_id}", response_model=ConcatTaskOut, summary="分镜拼接任务详情")
def get_concat(
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ConcatTaskOut:
    return _concat_out(_get_concat_task(db, task_id, current, PERM_VIDEO_VIEW))


@router.post("/video-concats/{task_id}/cancel", response_model=ConcatTaskOut, summary="取消分镜拼接任务")
def cancel_concat(
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ConcatTaskOut:
    et = _get_concat_task(db, task_id, current, PERM_VIDEO_EDIT)
    if et.status in ("queued", "running"):
        et.status = "cancelled"
        db.commit()
    db.refresh(et)
    return _concat_out(et)


@router.post("/video-concats/{task_id}/retry", response_model=ConcatTaskOut, summary="重试分镜拼接任务")
def retry_concat(
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ConcatTaskOut:
    et = _get_concat_task(db, task_id, current, PERM_VIDEO_EDIT)
    if et.status not in ("failed", "cancelled"):
        raise ConflictError("仅失败或已取消的拼接任务可重试")
    et.status = "queued"
    et.progress = 0
    et.error_message = None
    db.commit()
    dispatch_concat(db, et)
    db.refresh(et)
    return _concat_out(et)


@router.get("/video-concats/{task_id}/download", response_model=None, summary="下载拼接成片")
def download_concat(
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    et = _get_concat_task(db, task_id, current, PERM_VIDEO_VIEW)
    if not et.output_key or not storage.exists(et.output_key):
        raise NotFoundError("拼接成片不存在")
    data = storage.load(et.output_key)
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="concat_{et.id[:8]}.mp4"'},
    )
