"""任务调度辅助：统一的 RenderTask 创建、状态更新与（同步/异步）分发。

- USE_CELERY=true  时通过 Celery 异步执行，任务状态实时写入数据库。
- USE_CELERY=false 时同步执行（本地无 Redis 的降级模式），同样更新数据库。
前端只需轮询 RenderTask 状态接口，即可获得一致的体验。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.render_task import RenderTask

logger = get_logger(__name__)
_local_long_task_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fastvideo-local-task")


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
        # 本地开发通常没有 Redis/Celery。文档解析和整篇解说词都可能运行数分钟，
        # 不能在 FastAPI 请求线程里同步执行，否则前端会等到 300 秒后报 timeout。
        use_local_background = task.task_type == "parse_document" or (
            task.task_type == "gen_narration"
            and not (task.params or {}).get("regenerate_shot_id")
            and settings.ai_llm_provider not in {"disabled", "mock"}
        )
        if use_local_background:
            # Long-document evidence extraction can run for several minutes.
            # Keep the HTTP request responsive when Redis/Celery is disabled.
            _local_long_task_executor.submit(_run_local_background, task.id, sync_func)
            logger.info("task_dispatched_local_background", task_id=task.id)
        else:
            _run_sync_fallback(db, task, sync_func)
    return task


def _run_local_background(task_id: str, sync_func: Callable) -> None:
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            logger.error("local_background_task_missing", task_id=task_id)
            return
        _run_sync_fallback(db, task, sync_func)
    finally:
        db.close()


def recover_local_narration_tasks() -> int:
    """Restart local DeepSeek narration jobs left unfinished by a process restart."""
    if settings.use_celery or settings.ai_llm_provider in {"disabled", "mock"}:
        return 0

    from app.tasks.narration import gen_narration_sync

    db = SessionLocal()
    try:
        tasks = (
            db.query(RenderTask)
            .filter(
                RenderTask.task_type == "gen_narration",
                RenderTask.status.in_(["queued", "running", "retry"]),
            )
            .order_by(RenderTask.created_at.asc())
            .all()
        )
        for task in tasks:
            _local_long_task_executor.submit(_run_local_background, task.id, gen_narration_sync)
        if tasks:
            logger.info("local_narration_tasks_recovered", count=len(tasks))
        return len(tasks)
    finally:
        db.close()


def _run_sync_fallback(db: Session, task: RenderTask, sync_func: Callable) -> None:
    """同步降级执行（不阻塞请求太久的前提下）。"""
    try:
        from app.services.ai_configuration import refresh_runtime_config_from_db

        refresh_runtime_config_from_db()
        task.status = "running"
        task.attempts += 1
        db.commit()
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
