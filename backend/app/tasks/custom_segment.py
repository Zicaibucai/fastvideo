"""自定义合成任务（Celery + 同步降级）。

同步路径由 task_runner.run_task 管理 RenderTask 状态；
Celery 路径在本文件的包装里管理，行为与 render_segment_task 一致。
"""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.render_task import RenderTask
from app.services.custom_segment_service import render_custom_segment
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def custom_segment_sync(params: dict[str, Any]) -> dict[str, Any]:
    """同步降级入口：dispatch 约定 params 字典，状态由 run_task 管理。"""
    db = SessionLocal()
    try:
        return render_custom_segment(db, params["task_id"])
    finally:
        db.close()


@celery_app.task(bind=True, name="fastvideo.custom_segment", max_retries=2, default_retry_delay=10)
def custom_segment_task(self, task_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError(f"任务不存在: {task_id}")
        if task.status == "cancelled":
            return {"status": "cancelled"}
        task.status = "running"
        task.attempts += 1
        task.error_message = None
        task.message = "自定义合成已开始…"
        db.commit()
        result = render_custom_segment(db, task_id)
        task.status = "success"
        task.progress = 100
        task.result = result
        task.message = "处理完成"
        db.commit()
        return result
    except Exception as exc:
        task = db.get(RenderTask, task_id)
        if task:
            if task.status == "cancelled":
                return {"status": "cancelled"}
            task.status = "failed"
            task.error_message = str(exc)[:2000]
            task.message = "自定义合成失败"
            db.commit()
        logger.exception("custom_segment_task_failed", task_id=task_id)
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
