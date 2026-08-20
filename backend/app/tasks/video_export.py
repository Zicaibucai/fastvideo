"""视频合成与分段渲染任务（Phase 5）。

- compose_project：全片合成（读取 ExportTask）
- render_segment：单分镜渲染（RenderTask 包装）
- 同步降级（USE_CELERY=false）时直接执行
"""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.export_task import ExportTask
from app.models.render_task import RenderTask
from app.services.video_project_service import compose_project, render_segment
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


# ============================================================
# 全片合成
# ============================================================

def _run_compose(export_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        et = db.get(ExportTask, export_id)
        if not et:
            raise RuntimeError("导出任务不存在")
        if et.status == "cancelled":
            return {"status": "cancelled"}
        et.status = "running"
        et.progress = 20
        et.error_message = None
        db.commit()
        result = compose_project(db, export_id)
        db.refresh(et)
        et.status = "success"
        et.progress = 100
        et.output_key = result.get("output_key")
        et.output_url = f"/files/{result['output_key']}" if result.get("output_key") else None
        et.srt_key = result.get("srt_key")
        et.report_key = result.get("report_key")
        et.duration_seconds = result.get("duration")
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        et = db.get(ExportTask, export_id)
        if et:
            et.status = "failed"
            et.error_message = str(exc)[:2000]
            et.progress = 0
            db.commit()
        logger.exception("compose_project_failed", export_id=export_id)
        raise
    finally:
        db.close()


def compose_project_sync(params: dict[str, Any]) -> dict[str, Any]:
    """同步降级入口。"""
    return _run_compose(params["export_id"])


@celery_app.task(bind=True, name="fastvideo.compose_project", max_retries=2, default_retry_delay=15)
def compose_project_task(self, export_id: str) -> dict[str, Any]:
    try:
        return _run_compose(export_id)
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


# ============================================================
# 单分镜渲染
# ============================================================

def _run_segment_render(segment_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        from app.models.video_segment import VideoSegment

        seg = db.get(VideoSegment, segment_id)
        if not seg:
            raise RuntimeError("分段不存在")
        if seg.render_status == "cancelled":
            return {"status": "cancelled"}
        seg.render_status = "running"
        db.commit()
        result = render_segment(db, segment_id)
        return result
    except Exception as exc:
        logger.exception("segment_render_failed", segment_id=segment_id)
        raise
    finally:
        db.close()


def render_segment_sync(params: dict[str, Any]) -> dict[str, Any]:
    """同步降级入口：dispatch 约定 params 字典。"""
    db = SessionLocal()
    try:
        segment_id = params["segment_id"]
        task_id = params.get("task_id")
        result = render_segment(db, segment_id)
        if task_id and params.get("parent_task_id"):
            try:
                _refresh_batch_progress(db, params["parent_task_id"])
            except Exception:  # noqa: BLE001
                pass
        return result
    finally:
        db.close()


@celery_app.task(bind=True, name="fastvideo.render_segment", max_retries=2, default_retry_delay=10)
def render_segment_task(self, segment_id: str) -> dict[str, Any]:
    try:
        return _run_segment_render(segment_id)
    except Exception as exc:
        db = SessionLocal()
        try:
            from app.models.video_segment import VideoSegment

            seg = db.get(VideoSegment, segment_id)
            if seg:
                seg.render_status = "failed"
                seg.error_message = str(exc)[:2000]
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


# ============================================================
# 批量渲染进度
# ============================================================

def _refresh_batch_progress(db, parent_task_id: str | None) -> None:
    if not parent_task_id:
        return
    try:
        from app.services.video_project_service import refresh_render_batch_progress

        refresh_render_batch_progress(db, parent_task_id)
    except Exception:  # noqa: BLE001
        logger.warning("render_batch_progress_refresh_failed", parent=parent_task_id)
