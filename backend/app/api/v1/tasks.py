"""渲染任务路由：状态查询、重试、取消。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.user import User
from app.schemas.task import RenderTaskOut, TaskCancelRequest, TaskRetryRequest
from app.services.permissions import (
    accessible_project_ids,
    get_project_access,
    PERM_PROJECT_VIEW,
    PERM_TASK_UPDATE,
)

router = APIRouter(prefix="/tasks", tags=["渲染任务"])


def _get_owned_task(
    db: Session,
    task_id: str,
    user: User,
    project_id: str | None = None,
    permission: str = PERM_PROJECT_VIEW,
) -> RenderTask:
    task = db.get(RenderTask, task_id)
    if not task:
        raise NotFoundError("任务不存在")
    if project_id and task.project_id != project_id:
        raise NotFoundError("任务不存在")
    # 校验项目归属与权限（统一权限服务）
    if task.project_id:
        get_project_access(db, task.project_id, user, permission)
    return task


@router.get("", response_model=list[RenderTaskOut], summary="任务列表")
def list_tasks(
    project_id: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[RenderTask]:
    query = db.query(RenderTask)
    if project_id:
        query = query.filter(RenderTask.project_id == project_id)
    if status:
        query = query.filter(RenderTask.status == status)
    if task_type:
        query = query.filter(RenderTask.task_type == task_type)
    # 只能看到自己可访问项目下的任务（超管不过滤）
    project_ids = accessible_project_ids(db, current)
    if project_ids is not None:
        query = query.filter(RenderTask.project_id.in_(project_ids))
    return query.order_by(RenderTask.created_at.desc()).limit(min(limit, 200)).all()


@router.get("/{task_id}", response_model=RenderTaskOut, summary="任务详情（轮询）")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderTask:
    return _get_owned_task(db, task_id, current)


@router.post("/{task_id}/retry", response_model=RenderTaskOut, summary="重试失败任务")
def retry_task(
    task_id: str,
    payload: TaskRetryRequest | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderTask:
    task = _get_owned_task(db, task_id, current, permission=PERM_TASK_UPDATE)
    if task.status != "failed":
        # 也允许重试 queued/running（幂等）
        pass
    task.status = "queued"
    task.error_message = None
    task.progress = 0
    db.commit()
    db.refresh(task)

    # 重新入队
    from app.services.task_runner import dispatch
    from app.tasks.assets import gen_image_sync, gen_image_task, gen_tts_sync, gen_tts_task, gen_video_sync, gen_video_task
    from app.tasks.document_parse import parse_document_sync, parse_document_task
    from app.tasks.narration import gen_narration_sync, gen_narration_task
    from app.tasks.export import export_video_sync, export_video_task
    from app.tasks.video_export import compose_project_sync, compose_project_task, render_segment_sync, render_segment_task
    from app.tasks.voice import gen_voice_version_sync, gen_voice_version_task

    mapping = {
        "parse_document": (parse_document_task, parse_document_sync),
        "gen_narration": (gen_narration_task, gen_narration_sync),
        "gen_image": (gen_image_task, gen_image_sync),
        "gen_tts": (gen_tts_task, gen_tts_sync),
        "gen_video": (gen_video_task, gen_video_sync),
        "gen_voice_version": (gen_voice_version_task, gen_voice_version_sync),
        "segment_render": (render_segment_task, render_segment_sync),
        "compose_video": (compose_project_task, compose_project_sync),
        "export": (export_video_task, export_video_sync),
    }
    if task.task_type not in mapping:
        # Never leave an unsupported parent task silently queued forever.
        task.status = "failed"
        task.error_message = "该任务类型不支持单任务重试，请在对应页面重试批量任务"
        task.message = "暂不支持重试"
        db.commit()
        raise ConflictError(task.error_message)
    async_func, sync_func = mapping[task.task_type]
    dispatch(db, task=task, async_func=async_func, sync_func=sync_func)
    db.refresh(task)
    return task


@router.post("/{task_id}/cancel", response_model=RenderTaskOut, summary="取消任务")
def cancel_task(
    task_id: str,
    payload: TaskCancelRequest | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderTask:
    task = _get_owned_task(db, task_id, current, permission=PERM_TASK_UPDATE)
    if task.status in ("queued", "running"):
        task.status = "cancelled"
        task.message = "任务已取消"
        # 尝试撤销 Celery 任务
        if task.celery_task_id:
            try:
                from app.tasks.celery_app import celery_app

                celery_app.control.revoke(task.celery_task_id, terminate=False)
            except Exception:
                pass
        db.commit()
    db.refresh(task)
    return task
