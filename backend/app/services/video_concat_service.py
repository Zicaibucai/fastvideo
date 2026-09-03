"""分镜拼接服务：把多个现成视频素材（剪映成品、已合成分段等）按顺序拼接成整片。

与视频工程（VideoProject）的区别：不走分镜/分段模型，直接对素材库中的视频做
归一化（分辨率/帧率/音频轨统一）+ xfade 转场拼接，结果归档回素材库。
任务记录复用 ExportTask（video_project_id=None, mode="concat"）。
"""

from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.export_task import ExportTask
from app.models.project import Project
from app.models.user import User
from app.schemas.video import ConcatCreateIn
from app.services.video_composer import (
    concat_audio,
    concat_with_transitions,
    mux,
    probe_media,
)
from app.services.video_project_media import extract_audio, write_bytes
from app.services.video_project_service import (
    VideoProjectError,
    _persist_video_render_asset,
)

logger = get_logger(__name__)

CONCAT_ALLOWED_FPS = (24, 25, 30)


def create_concat_task(db: Session, project: Project, payload: ConcatCreateIn, user: User | None = None) -> ExportTask:
    """校验输入素材并创建拼接任务（queued）。"""
    if payload.fps not in CONCAT_ALLOWED_FPS:
        raise VideoProjectError("fps 仅支持 24/25/30")

    item_snapshots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload.items:
        if item.asset_id in seen:
            raise VideoProjectError("同一片段被重复添加，请调整顺序而不是重复选择")
        seen.add(item.asset_id)
        asset = db.get(Asset, item.asset_id)
        if not asset or asset.project_id != project.id:
            raise VideoProjectError("拼接素材不存在或不属于当前项目")
        if asset.asset_type != "video" or not asset.file_key:
            raise VideoProjectError(f"素材「{asset.name}」不是视频文件")
        data = storage.load(asset.file_key)
        info = probe_media(data, suffix=".mp4")
        if info.get("decodable") is False or not info.get("duration_seconds"):
            raise VideoProjectError(f"素材「{asset.name}」不是可解码的视频，请重新上传")
        item_snapshots.append({
            "asset_id": asset.id,
            "name": asset.name,
            "duration": info["duration_seconds"],
            "width": info.get("width"),
            "height": info.get("height"),
            "has_audio": info.get("has_audio"),
            "transition_type": item.transition_type,
            "transition_duration": item.transition_duration,
        })

    name = (payload.name or "").strip() or f"分镜拼接·{time.strftime('%m%d-%H%M')}"
    et = ExportTask(
        video_project_id=None,
        project_id=project.id,
        export_format="mp4",
        mode="concat",
        status="queued",
        progress=0,
        params={
            "name": name,
            "items": [
                {"asset_id": s["asset_id"], "transition_type": s["transition_type"], "transition_duration": s["transition_duration"]}
                for s in item_snapshots
            ],
            "width": payload.width,
            "height": payload.height,
            "fps": payload.fps,
        },
        timeline_snapshot={"name": name, "items": item_snapshots, "width": payload.width, "height": payload.height, "fps": payload.fps},
    )
    db.add(et)
    db.commit()
    db.refresh(et)
    return et


def _normalize_clip(src: Path, dst: Path, *, width: int, height: int, fps: int, has_audio: bool) -> None:
    """把任意输入统一为 width×height@fps、yuv420p、48kHz 立体声，供 xfade/acrossfade 使用。"""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p"
    )
    cmd = [settings.ffmpeg_binary, "-y", "-i", str(src)]
    if not has_audio:
        # 无音频流的素材补一条静音轨，保证后续 acrossfade 输入一致
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += [
        "-vf", vf,
        "-map", "0:v:0",
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
    ]
    if not has_audio:
        cmd += ["-shortest"]
    cmd += ["-movflags", "+faststart", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise VideoProjectError(f"片段归一化失败：{(proc.stderr or '')[-300:]}")


def run_concat(db: Session, export_id: str) -> dict[str, Any]:
    """执行拼接：归一化 → 转场拼接 → 音频拼接 → mux → 归档素材库。"""
    et = db.get(ExportTask, export_id)
    if not et:
        raise VideoProjectError("拼接任务不存在")
    if et.status == "cancelled":
        return {"status": "cancelled"}
    params = et.params or {}
    items_in = params.get("items") or []
    if len(items_in) < 2:
        raise VideoProjectError("至少需要两个视频才能拼接")
    w, h, fps = int(params.get("width") or 1920), int(params.get("height") or 1080), int(params.get("fps") or 25)

    et.status = "running"
    et.progress = 10
    et.error_message = None
    db.commit()

    with __import__("tempfile").TemporaryDirectory(prefix="fv_concat_") as td:
        tmp = Path(td)
        video_items: list[dict[str, Any]] = []
        audio_items: list[dict[str, Any]] = []

        for index, item in enumerate(items_in):
            asset = db.get(Asset, item["asset_id"])
            if not asset or not asset.file_key:
                raise VideoProjectError("拼接素材已被删除，请重新选择")
            raw = tmp / f"raw_{index}.mp4"
            write_bytes(raw, storage.load(asset.file_key))
            info = probe_media(raw.read_bytes(), suffix=".mp4")
            if info.get("decodable") is False or not info.get("duration_seconds"):
                raise VideoProjectError(f"素材「{asset.name}」不是可解码的视频，请重新上传")

            norm = tmp / f"norm_{index}.mp4"
            _normalize_clip(raw, norm, width=w, height=h, fps=fps, has_audio=bool(info.get("has_audio")))
            audio_path = tmp / f"audio_{index}.m4a"
            extract_audio(norm, audio_path)

            duration = float(info["duration_seconds"])
            video_items.append({
                "path": str(norm),
                "duration": duration,
                "transition_type": item.get("transition_type") or "none",
                "transition_duration": float(item.get("transition_duration") or 0.5),
            })
            audio_items.append({
                "path": str(audio_path),
                "duration": duration,
                "transition_type": item.get("transition_type") or "none",
                "transition_duration": float(item.get("transition_duration") or 0.5),
            })
            et.progress = 10 + round((index + 1) / len(items_in) * 40)
            db.commit()

        et.progress = 55
        db.commit()
        final_video, total = concat_with_transitions(video_items, width=w, height=h, fps=fps)
        mixed = concat_audio(audio_items, total)

        et.progress = 80
        db.commit()
        final_mp4 = mux(final_video, mixed, fps=fps)

        out_key = f"projects/{et.project_id}/concats/{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
        storage.save(out_key, final_mp4)
        render_asset = _persist_video_render_asset(
            db,
            project_id=et.project_id,
            name_prefix=params.get("name") or "分镜拼接",
            owner_key=f"concat:{et.id}",
            storage_key=out_key,
            data=final_mp4,
            duration=total,
            width=w,
            height=h,
            meta={
                "category": "分镜拼接",
                "concat_task_id": et.id,
                "kind": "concat_video",
                "clip_count": len(items_in),
            },
            tags=["分镜拼接", "拼接成片"],
        )

        et.status = "success"
        et.progress = 100
        et.output_key = out_key
        et.output_url = storage.url(out_key)
        et.file_size = len(final_mp4)
        et.duration_seconds = total
        db.commit()

        return {
            "status": "success",
            "output_key": out_key,
            "duration": total,
            "asset_id": render_asset.id,
            "version": (render_asset.meta or {}).get("version"),
        }


def dispatch_concat(db: Session, export_task: ExportTask) -> ExportTask:
    """拼接任务分发：USE_CELERY 异步，否则同步。"""
    from app.tasks.video_concat import concat_videos_sync, concat_videos_task

    if settings.use_celery:
        try:
            async_result = concat_videos_task.delay(export_task.id)
            export_task.celery_task_id = async_result.id
            db.commit()
        except Exception as exc:
            logger.warning("celery_concat_fallback_sync", error=str(exc))
            concat_videos_sync({"export_id": export_task.id})
    else:
        concat_videos_sync({"export_id": export_task.id})
    db.refresh(export_task)
    return export_task
