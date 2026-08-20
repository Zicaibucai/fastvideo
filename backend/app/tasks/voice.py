"""配音 Celery 任务 + 同步降级。

- gen_voice_version：单个分镜配音生成
- tts_batch 父任务：由 API 创建子任务后分发；父任务状态实时聚合
- 同步降级（USE_CELERY=false）时直接执行
"""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.render_task import RenderTask
from app.services.voice_service import generate_voice_version, refresh_batch_progress
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def _generate_version_from_params(db, params: dict[str, Any]) -> dict[str, Any]:
    version = generate_voice_version(
        db,
        project_id=params["project_id"],
        shot_id=params["shot_id"],
        voice_template_id=params.get("voice_template_id"),
        user_name=params.get("user_name"),
        speed_override=params.get("speed"),
        pitch_override=params.get("pitch"),
        volume_override=params.get("volume"),
        emotion_override=params.get("emotion"),
        pause_override=params.get("pause_strength"),
        normalized_text_override=params.get("normalized_text_override"),
        seed=params.get("seed"),
        output_formats=params.get("output_formats") or ["wav", "mp3"],
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "version_id": version.id,
        "version_number": version.version_number,
        "actual_duration_seconds": version.actual_duration_seconds,
        "duration_status": version.duration_status,
        "quality_status": version.quality_status,
        "is_mock": version.is_mock,
    }


def _refresh_parent(db, parent_task_id: str | None) -> None:
    if not parent_task_id:
        return
    try:
        refresh_batch_progress(db, parent_task_id)
    except Exception:  # noqa: BLE001
        logger.warning("batch_progress_refresh_failed", parent=parent_task_id)


def _run_voice_generation(task_id: str) -> dict[str, Any]:
    """Celery 执行入口：读取任务 params 并更新任务状态。"""
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError("配音任务不存在")
        if task.status == "cancelled":
            return {"status": "cancelled"}
        task.status = "running"
        task.progress = 10
        task.error_message = None
        db.commit()

        params = task.params or {}
        result = _generate_version_from_params(db, params)

        db.refresh(task)
        task.status = "success"
        task.progress = 100
        task.result = result
        task.message = "配音生成完成"
        db.commit()
        _refresh_parent(db, task.parent_task_id)
        return result
    except Exception as exc:
        db.rollback()
        task = db.get(RenderTask, task_id)
        if task:
            task.status = "failed"
            task.error_message = str(exc)[:2000]
            task.message = "配音生成失败"
            db.commit()
            _refresh_parent(db, task.parent_task_id)
        logger.exception("voice_generation_failed", task_id=task_id)
        raise
    finally:
        db.close()


def voice_generation_sync(params: dict[str, Any]) -> dict[str, Any]:
    """同步降级入口：dispatch 约定 params 字典。

    USE_CELERY=false 时，dispatch 的同步回退会调用本函数并负责更新任务状态。
    这里只负责执行生成并返回结果，同时刷新父任务进度。
    """
    db = SessionLocal()
    try:
        result = _generate_version_from_params(db, params)
        _refresh_parent(db, params.get("parent_task_id"))
        return result
    finally:
        db.close()


@celery_app.task(bind=True, name="fastvideo.gen_voice_version", max_retries=3, default_retry_delay=10)
def gen_voice_version_task(self, task_id: str) -> dict[str, Any]:
    try:
        return _run_voice_generation(task_id)
    except Exception as exc:
        # 用户取消后不得自动重试
        db = SessionLocal()
        try:
            task = db.get(RenderTask, task_id)
            if task and task.status == "cancelled":
                return {"status": "cancelled"}
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


gen_voice_version_sync = voice_generation_sync
