"""导出与视频合成任务：使用 FFmpeg 将分镜片段合成为最终投标视频。

- 若无可用片段（Mock 演示时未生成实际视频），则生成一段演示视频。
- 支持 16:9、1080P、水印。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.export_task import ExportTask
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.video_project import VideoProject
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


# ---------------- 核心合成逻辑 ----------------

def _compose_video(params: dict[str, Any]) -> dict[str, Any]:
    video_project_id = params["video_project_id"]
    export_format = params.get("export_format", "mp4")
    watermark = params.get("watermark_text")

    db = SessionLocal()
    try:
        vp = db.get(VideoProject, video_project_id)
        if not vp:
            raise RuntimeError("视频工程不存在")

        # 收集分镜片段（按 timeline 或分镜序号）
        shots = (
            db.query(StoryboardShot)
            .filter(StoryboardShot.project_id == vp.project_id, StoryboardShot.is_active.is_(True))
            .order_by(StoryboardShot.sequence.asc())
            .all()
        )
        clips: list[tuple[str, float]] = []
        for shot in shots:
            if shot.video_clip_key and storage.exists(shot.video_clip_key):
                clips.append((shot.video_clip_key, shot.duration_seconds or 5.0))

        width = vp.width or settings.video_width
        height = vp.height or settings.video_height
        fps = vp.fps or settings.video_fps

        # 无片段时生成演示视频
        if not clips:
            from app.adapters.video import generate_test_video

            data = generate_test_video(
                text=f"{vp.name}（演示）",
                duration=8.0,
                width=width,
                height=height,
                fps=fps,
            )
            key = f"projects/{vp.project_id}/video_projects/{vp.id}/preview.mp4"
            storage.save(key, data)
            vp.status = "success"
            vp.output_key = key
            vp.output_url = storage.url(key)
            vp.duration_seconds = 8.0
            db.commit()
            return {"output_key": key, "duration": 8.0}

        # 用 FFmpeg concat 合成
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            list_file = tmp_path / "concat.txt"
            # 先下载所有片段
            with list_file.open("w", encoding="utf-8") as f:
                for i, (key, _) in enumerate(clips):
                    local = tmp_path / f"clip{i}.mp4"
                    local.write_bytes(storage.load(key))
                    f.write(f"file '{local.resolve()}'\n")

            output_local = tmp_path / f"output.{export_format}"
            cmd = [
                settings.ffmpeg_binary,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
            ]
            if watermark:
                cmd += ["-vf", f"drawtext=text='{watermark}':fontcolor=white@0.6:fontsize=36:x=w-tw-40:y=h-th-40"]
            cmd.append(str(output_local))

            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            except subprocess.CalledProcessError as exc:
                logger.warning("ffmpeg_concat_failed", stderr=exc.stderr.decode()[:500])
                raise RuntimeError(f"FFmpeg 合成失败: {exc}")
            except FileNotFoundError:
                raise RuntimeError("未找到 ffmpeg，请安装 FFmpeg。")

            data = output_local.read_bytes()
            key = f"projects/{vp.project_id}/video_projects/{vp.id}/final.{export_format}"
            storage.save(key, data)
            duration = sum(d for _, d in clips)

            vp.status = "success"
            vp.output_key = key
            vp.output_url = storage.url(key)
            vp.duration_seconds = duration
            db.commit()
            return {"output_key": key, "duration": duration}
    finally:
        db.close()


# ---------------- Celery 导出任务 ----------------

def _run_export(task_id: str, fn) -> dict:
    db = SessionLocal()
    try:
        task = db.get(ExportTask, task_id)
        if not task:
            raise RuntimeError("导出任务不存在")
        task.status = "running"
        task.attempts += 1
        db.commit()
        result = fn(task.params or {})
        db.refresh(task)
        task.status = "success"
        task.progress = 100
        task.output_key = result.get("output_key")
        task.output_url = storage.url(result["output_key"]) if result.get("output_key") else None
        task.duration_seconds = result.get("duration")
        db.commit()
        return result
    finally:
        db.close()


@celery_app.task(bind=True, name="fastvideo.export_video", max_retries=3, default_retry_delay=15)
def export_video_task(self, task_id: str) -> dict:
    try:
        return _run_export(task_id, _compose_video)
    except Exception as exc:
        db = SessionLocal()
        try:
            task = db.get(ExportTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)[:2000]
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


export_video_sync = _compose_video
