"""AI 视频生成任务：Celery + 同步降级。"""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.video_generation import VideoGenerationJob
from app.services.video_gen_service import run_video_job
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def _execute(job_id: str) -> dict[str, Any]:
    return run_video_job(job_id)


def video_gen_job_sync(params: dict[str, Any]) -> dict[str, Any]:
    """同步降级入口（与 dispatch 约定 params 字典）。"""
    job_id = params.get("job_id")
    return run_video_job(str(job_id))


@celery_app.task(
    bind=True, name="fastvideo.video_gen_job", max_retries=2, default_retry_delay=10
)
def video_gen_job_task(self, job_id: str) -> dict[str, Any]:
    try:
        return _execute(job_id)
    except Exception as exc:
        db = SessionLocal()
        try:
            job = db.get(VideoGenerationJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:2000]
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc
