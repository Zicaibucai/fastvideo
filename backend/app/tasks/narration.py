"""解说词生成任务（使用智能拆解引擎）。

async 版供 Celery worker 调用；sync 版供本地无 Redis 时降级调用。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.render_task import RenderTask
from app.services.narration_engine import generate_storyboard, regenerate_single_shot
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


# ---------------- Celery 任务 ----------------

@celery_app.task(bind=True, name="fastvideo.gen_narration", max_retries=3, default_retry_delay=10)
def gen_narration_task(self, task_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError("任务不存在")

        task.status = "running"
        task.attempts += 1
        db.commit()

        try:
            if task.params.get("regenerate_shot_id"):
                result = regenerate_single_shot(task.params)
            else:
                result = generate_storyboard(task.params)
            db.refresh(task)
            task.status = "success"
            task.progress = 100
            task.result = result
            task.message = "解说词生成完成"
            db.commit()
            return result
        except Exception as exc:
            db.refresh(task)
            task.status = "failed"
            task.error_message = str(exc)[:2000]
            task.message = "生成失败"
            db.commit()
            raise self.retry(exc=exc) from exc
    finally:
        db.close()


def gen_narration_sync(params: dict[str, Any]) -> dict[str, Any]:
    if params.get("regenerate_shot_id"):
        return regenerate_single_shot(params)
    return generate_storyboard(params)
