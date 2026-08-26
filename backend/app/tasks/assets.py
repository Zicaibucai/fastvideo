"""素材生成任务：图片生成、TTS 配音、视频生成。

三种任务共用同一套 状态更新 + 重试 机制。
"""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from app.adapters.factory import get_image_adapter, get_tts_adapter, get_video_adapter
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


# ---------------- 共用执行器 ----------------

def _run_with_status(task_id: str, fn: Callable[[dict], dict]) -> dict:
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError("任务不存在")
        task.status = "running"
        task.attempts += 1
        db.commit()
        result = fn(task.params or {})
        db.refresh(task)
        task.status = "success"
        task.progress = 100
        task.result = result
        task.message = "完成"
        db.commit()
        return result
    finally:
        db.close()


# ---------------- 图片生成 ----------------

def _gen_image(params: dict[str, Any]) -> dict[str, Any]:
    project_id = params.get("project_id")
    prompt = params.get("prompt") or "建筑工程场景"

    adapter = get_image_adapter()
    if not adapter.is_available():
        raise RuntimeError("图片生成服务不可用，请检查配置。")

    images = adapter.generate(prompt, n=1)
    data = images[0] if images else b""
    key = f"projects/{project_id}/render-assets/legacy-{uuid4().hex}.png"
    storage.save(key, data)

    db = SessionLocal()
    try:
        shot_id = params.get("shot_id")
        shot = db.get(StoryboardShot, shot_id) if shot_id else None
        if shot_id and (not shot or shot.project_id != project_id):
            raise RuntimeError("分镜不存在")
        asset = Asset(
            project_id=project_id,
            name="AI 渲染图（旧任务）",
            asset_type="image",
            source="ai_image",
            file_key=key,
            file_size=len(data),
            mime_type="image/png",
            generated_by=adapter.provider,
            prompt=prompt,
            is_ai_generated=True,
            ai_disclaimer=(
                "Mock Render：演示生成图片，禁止用于正式投标。"
                if adapter.provider == "mock"
                else "AI渲染图仅用于视觉表达，工程信息以原始模型、图纸及施工方案为准。"
            ),
            meta={"is_mock": adapter.provider == "mock"},
        )
        db.add(asset)
        db.flush()
        if shot:
            shot.image_asset_id = asset.id
            shot.visual_review_status = "pending"
        db.commit()
        return {"asset_id": asset.id, "file_key": key}
    finally:
        db.close()


# ---------------- TTS 配音 ----------------

def _gen_tts(params: dict[str, Any]) -> dict[str, Any]:
    shot_id = params["shot_id"]
    project_id = params.get("project_id")
    text = params.get("text") or "配音文本"
    voice = params.get("voice_name", "onyx")
    speed = float(params.get("speed", 1.0))

    adapter = get_tts_adapter()
    if not adapter.is_available():
        raise RuntimeError("TTS 服务不可用，请检查配置。")

    data = adapter.synthesize(text, voice=voice, speed=speed)
    key = f"projects/{project_id}/shots/{shot_id}/voice.mp3"
    storage.save(key, data)

    db = SessionLocal()
    try:
        shot = db.get(StoryboardShot, shot_id)
        if not shot:
            raise RuntimeError("分镜不存在")
        asset = Asset(
            project_id=project_id,
            name=f"分镜{shot.sequence} 配音",
            asset_type="audio",
            source="ai_tts",
            file_key=key,
            file_size=len(data),
            mime_type="audio/mpeg",
            generated_by=adapter.provider,
            prompt=text,
            meta={"voice": voice, "speed": speed, "is_mock": adapter.provider == "mock"},
        )
        db.add(asset)
        db.flush()
        shot.audio_asset_id = asset.id
        shot.tts_voice_id = voice
        db.commit()
        return {"asset_id": asset.id, "file_key": key}
    finally:
        db.close()


# ---------------- 视频生成 ----------------

def _gen_video(params: dict[str, Any]) -> dict[str, Any]:
    project_id = params.get("project_id")
    prompt = params.get("prompt") or "工程演示视频"
    duration = float(params.get("duration", 5.0))

    adapter = get_video_adapter()
    if not adapter.is_available():
        raise RuntimeError("视频生成服务不可用，请检查配置。")

    data = adapter.generate(
        prompt,
        duration=duration,
    )
    key = f"projects/{project_id}/video-assets/legacy-{uuid4().hex}.mp4"
    storage.save(key, data)

    db = SessionLocal()
    try:
        asset = Asset(
            project_id=project_id,
            name="AI 视频（旧任务）",
            asset_type="video",
            source="ai_video",
            file_key=key,
            file_size=len(data),
            mime_type="video/mp4",
            duration_seconds=duration,
            generated_by=adapter.provider,
            prompt=prompt,
            meta={
                "generation_mode": "text_to_video",
                "requested_duration": duration,
                "is_mock": adapter.provider == "mock",
            },
        )
        db.add(asset)
        db.flush()
        db.commit()
        return {"asset_id": asset.id, "file_key": key}
    finally:
        db.close()


# ---------------- Celery 任务注册 ----------------

@celery_app.task(bind=True, name="fastvideo.gen_image", max_retries=3, default_retry_delay=10)
def gen_image_task(self, task_id: str) -> dict:
    try:
        return _run_with_status(task_id, _gen_image)
    except Exception as exc:
        db = SessionLocal()
        try:
            task = db.get(RenderTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)[:2000]
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, name="fastvideo.gen_tts", max_retries=3, default_retry_delay=10)
def gen_tts_task(self, task_id: str) -> dict:
    try:
        return _run_with_status(task_id, _gen_tts)
    except Exception as exc:
        db = SessionLocal()
        try:
            task = db.get(RenderTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)[:2000]
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, name="fastvideo.gen_video", max_retries=3, default_retry_delay=10)
def gen_video_task(self, task_id: str) -> dict:
    try:
        return _run_with_status(task_id, _gen_video)
    except Exception as exc:
        db = SessionLocal()
        try:
            task = db.get(RenderTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)[:2000]
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


# 同步降级入口（USE_CELERY=false 时使用）
gen_image_sync = _gen_image
gen_tts_sync = _gen_tts
gen_video_sync = _gen_video
