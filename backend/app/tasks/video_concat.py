"""分镜拼接任务（Celery + 同步降级）。"""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.export_task import ExportTask
from app.services.video_concat_service import run_concat
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def _run_concat(export_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        et = db.get(ExportTask, export_id)
        if not et:
            raise RuntimeError("拼接任务不存在")
        if et.status == "cancelled":
            return {"status": "cancelled"}
        return run_concat(db, export_id)
    except Exception as exc:
        db.rollback()
        et = db.get(ExportTask, export_id)
        if et:
            et.status = "failed"
            et.error_message = str(exc)[:2000]
            et.progress = 0
            db.commit()
        logger.exception("video_concat_failed", export_id=export_id)
        raise
    finally:
        db.close()


def concat_videos_sync(params: dict[str, Any]) -> dict[str, Any]:
    """同步降级入口。失败时异常由 _run_concat 落库后在此吞掉，与导出同步路径行为一致。"""
    try:
        return _run_concat(params["export_id"])
    except Exception:  # noqa: BLE001
        return {"status": "failed"}


@celery_app.task(bind=True, name="fastvideo.concat_videos", max_retries=2, default_retry_delay=15)
def concat_videos_task(self, export_id: str) -> dict[str, Any]:
    try:
        return _run_concat(export_id)
    except Exception as exc:
        # 用户取消后不得自动重试
        db = SessionLocal()
        try:
            et = db.get(ExportTask, export_id)
            if et and et.status == "cancelled":
                return {"status": "cancelled"}
        finally:
            db.close()
        raise self.retry(exc=exc) from exc
