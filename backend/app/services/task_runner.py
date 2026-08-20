"""任务调度辅助：统一的 RenderTask 创建、状态更新与（同步/异步）分发。

- USE_CELERY=true  时通过 Celery 异步执行，任务状态实时写入数据库。
- USE_CELERY=false 时同步执行（本地无 Redis 的降级模式），同样更新数据库。
前端只需轮询 RenderTask 状态接口，即可获得一致的体验。
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.render_task import RenderTask

logger = get_logger(__name__)


def create_render_task(
    db: Session,
    *,
    project_id: str | None,
    task_type: str,
    params: dict | None = None,
    shot_id: str | None = None,
    message: str | None = None,
    max_attempts: int = 3,
) -> RenderTask:
    task = RenderTask(
        project_id=project_id,
        shot_id=shot_id,
        task_type=task_type,
        status="queued",
        progress=0,
        params=params or {},
        message=message or _default_message(task_type),
        max_attempts=max_attempts,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _default_message(task_type: str) -> str:
    return {
        "parse_document": "解析招标资料中…",
        "gen_narration": "AI 生成解说词中…",
        "gen_image": "AI 生成画面中…",
        "gen_video": "AI 生成视频中…",
        "gen_tts": "AI 配音生成中…",
        "compose_video": "视频合成中…",
        "export": "导出视频中…",
    }.get(task_type, "任务处理中…")


def run_task(
    db: Session,
    task_id: str,
    fn: Callable[[dict[str, Any]], dict[str, Any]],
    on_progress: Callable[[int, str | None], None] | None = None,
) -> dict[str, Any]:
    """同步执行任务主体并更新 RenderTask 状态。"""
    task = db.get(RenderTask, task_id)
    if not task:
        raise RuntimeError(f"任务不存在: {task_id}")

    task.status = "running"
    task.attempts += 1
    db.commit()

    try:
        if on_progress:
            on_progress(5, "开始处理…")
        result = fn(task.params or {})
        task.status = "success"
        task.progress = 100
        task.result = result
        task.message = "处理完成"
        task.error_message = None
        db.commit()
        return result
    except Exception as exc:
        logger.exception("task_failed", task_id=task_id, type=task.task_type)
        task.status = "failed"
        task.error_message = str(exc)[:2000]
        task.message = "处理失败"
        db.commit()
        raise


def dispatch(
    db: Session,
    *,
    task: RenderTask,
    async_func: Callable,
    sync_func: Callable,
) -> RenderTask:
    """统一分发：USE_CELERY 时走异步，否则同步执行。"""
    if settings.use_celery:
        try:
            async_result = async_func.delay(task.id)
            task.celery_task_id = async_result.id
            db.commit()
            logger.info("task_dispatched", task_id=task.id, celery=async_result.id)
        except Exception as exc:
            # Redis 不可用 -> 降级同步
            logger.warning("celery_unavailable_fallback_sync", error=str(exc))
            _run_sync_fallback(db, task, sync_func)
    else:
        _run_sync_fallback(db, task, sync_func)
    return task


def _run_sync_fallback(db: Session, task: RenderTask, sync_func: Callable) -> None:
    """同步降级执行（不阻塞请求太久的前提下）。"""
    try:
        result = sync_func(task.params or {})
        db.refresh(task)
        task.status = "success"
        task.progress = 100
        task.result = result
        task.message = "处理完成"
        db.commit()
    except Exception as exc:
        logger.exception("sync_task_failed", task_id=task.id)
        db.refresh(task)
        task.status = "failed"
        task.error_message = str(exc)[:2000]
        task.message = "处理失败"
        db.commit()
