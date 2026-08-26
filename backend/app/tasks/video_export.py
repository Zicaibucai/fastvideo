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

def _run_segment_render(identifier: str) -> dict[str, Any]:
    # Keep a safe value for error logging even if task lookup itself fails.
    segment_id = identifier
    db = SessionLocal()
    try:
        from app.models.video_segment import VideoSegment

        # Celery 分发约定传入 RenderTask.id；同步降级入口则传入 VideoSegment.id。
        # 两种入口统一解析，避免把任务 ID 当成分段 ID 查询。
        task = db.get(RenderTask, identifier)
        segment_id = (
            (task.params or {}).get("segment_id")
            if task and task.task_type == "segment_render"
            else identifier
        )
        seg = db.get(VideoSegment, segment_id)
        if not seg:
            raise RuntimeError(f"分段不存在: {segment_id}")
        if seg.render_status == "cancelled":
            return {"status": "cancelled"}
        task = task or _segment_render_task(db, segment_id)
        if task:
            task.status = "running"
            task.progress = max(task.progress, 5)
            task.attempts += 1
            task.error_message = None
            task.message = "分段合成已开始…"
            db.commit()
        seg.render_status = "running"
        db.commit()
        result = render_segment(db, segment_id)
        if task:
            task.status = "success"
            task.progress = 100
            task.result = result
            task.message = "处理完成"
            db.commit()
        return result
    except Exception as exc:
        task = locals().get("task")
        if task:
            task.status = "failed"
            task.progress = 0
            task.error_message = str(exc)[:2000]
            task.message = "分段合成失败"
            db.commit()
        logger.exception("segment_render_failed", segment_id=segment_id)
        raise
    finally:
        db.close()


def _segment_render_task(db, segment_id: str) -> RenderTask | None:
    tasks = (
        db.query(RenderTask)
        .filter(RenderTask.task_type == "segment_render")
        .order_by(RenderTask.created_at.desc())
        .all()
    )
    for task in tasks:
        if (task.params or {}).get("segment_id") == segment_id and task.status in {"queued", "running"}:
            return task
    return None


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
def render_segment_task(self, task_id: str) -> dict[str, Any]:
    try:
        return _run_segment_render(task_id)
    except Exception as exc:
        db = SessionLocal()
        try:
            from app.models.video_segment import VideoSegment

            # The Celery argument is a RenderTask ID. Resolve the actual
            # segment before updating its status on a terminal failure.
            render_task = db.get(RenderTask, task_id)
            actual_segment_id = (
                (render_task.params or {}).get("segment_id")
                if render_task and render_task.task_type == "segment_render"
                else task_id
            )
            seg = db.get(VideoSegment, actual_segment_id)
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
