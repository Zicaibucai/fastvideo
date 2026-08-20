"""渲染任务路由：状态查询、重试、取消。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.user import User
from app.schemas.task import RenderTaskOut, TaskCancelRequest, TaskRetryRequest

router = APIRouter(prefix="/tasks", tags=["渲染任务"])


def _get_owned_task(db: Session, task_id: str, user: User, project_id: str | None = None) -> RenderTask:
    task = db.get(RenderTask, task_id)
    if not task:
        raise NotFoundError("任务不存在")
    if project_id and task.project_id != project_id:
        raise NotFoundError("任务不存在")
    # 校验项目归属
    if task.project_id:
        project = db.get(Project, task.project_id)
        if not project or project.owner_id != user.id:
            raise NotFoundError("任务不存在")
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
    # 只能看到自己项目下的任务
    owned_project_ids = [
        p.id for p in db.query(Project).filter(Project.owner_id == current.id).all()
    ]
    query = query.filter(RenderTask.project_id.in_(owned_project_ids))
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
    task = _get_owned_task(db, task_id, current)
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

    mapping = {
        "parse_document": (parse_document_task, parse_document_sync),
        "gen_narration": (gen_narration_task, gen_narration_sync),
        "gen_image": (gen_image_task, gen_image_sync),
        "gen_tts": (gen_tts_task, gen_tts_sync),
        "gen_video": (gen_video_task, gen_video_sync),
    }
    if task.task_type in mapping:
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
    task = _get_owned_task(db, task_id, current)
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
