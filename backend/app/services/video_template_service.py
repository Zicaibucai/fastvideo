"""从专业视频创建 AI 视频模板的媒体处理与配方辅助。"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.video_generation import VideoTemplateDraft
from app.services.video_composer import probe_media

logger = get_logger(__name__)


def _probe_path(path: str) -> dict[str, Any]:
    """读取视频元数据，不把整段上传视频复制到 Python 内存。"""
    cmd = [
        settings.ffprobe_binary,
        "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of", "json",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 ffprobe，请安装 FFmpeg。") from exc
    if proc.returncode != 0:
        raise RuntimeError("无法读取视频元数据")
    payload = json.loads(proc.stdout or "{}")
    stream = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), {})
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    fps = 0.0
    raw_fps = stream.get("r_frame_rate")
    if raw_fps and "/" in raw_fps:
        try:
            num, den = raw_fps.split("/", 1)
            fps = float(num) / max(float(den), 1.0)
        except (TypeError, ValueError, ZeroDivisionError):
            fps = 0.0
    width = stream.get("width")
    height = stream.get("height")
    return {
        "duration_seconds": round(duration, 3),
        "width": int(width) if width else None,
        "height": int(height) if height else None,
        "fps": round(fps, 3) if fps else None,
    }


def inspect_source_video(db: Session, asset: Asset) -> dict[str, Any]:
    if asset.asset_type != "video" or not asset.file_key:
        raise ValueError("模板来源必须是项目中的视频素材")
    source_path = storage.local_path(asset.file_key)
    try:
        info = _probe_path(source_path)
    finally:
        storage.release_local_path(source_path)
    if not info.get("duration_seconds"):
        raise ValueError("视频没有可读取的时长")
    asset.duration_seconds = info["duration_seconds"]
    asset.width = info.get("width")
    asset.height = info.get("height")
    if info.get("width") and info.get("height"):
        asset.aspect_ratio = f"{info['width']}:{info['height']}"
    asset.meta = {**(asset.meta or {}), "video_metadata": info}
    db.flush()
    return info


def _validate_clip_times(
    duration: float,
    clip_start: float,
    clip_end: float,
) -> tuple[float, float]:
    if clip_start < 0 or clip_end <= clip_start:
        raise ValueError("镜头起止时间不正确")
    if clip_end > duration + 0.05:
        raise ValueError("镜头结束时间不能超过视频时长")
    clip_length = clip_end - clip_start
    if clip_length < 2:
        raise ValueError("模板片段至少需要 2 秒")
    if clip_length > 15:
        raise ValueError("模板片段不能超过 15 秒")
    return round(clip_start, 3), round(clip_end, 3)


def _normalize_reference_times(
    clip_start: float,
    clip_end: float,
    middle: float | list[float] | None,
) -> list[float]:
    """校验首帧之后的有序参考帧，最多支持 8 张（加首帧共 9 张）。"""
    if middle is None:
        values: list[float] = []
    elif isinstance(middle, list):
        values = [float(value) for value in middle]
    else:
        values = [float(middle)]
    if len(values) > 8:
        raise ValueError("首帧之后最多可添加 8 张中间/参考帧")
    normalized: list[float] = []
    for value in values:
        rounded = round(value, 3)
        if rounded <= clip_start or rounded > clip_end + 0.05:
            raise ValueError("参考帧必须位于首帧之后且不能超过尾帧时间")
        if any(abs(existing - rounded) < 0.001 for existing in normalized):
            raise ValueError("参考帧时间不能重复")
        normalized.append(rounded)
    return normalized


def _extract_frame(source_path: str, timestamp: float) -> bytes:
    with tempfile.TemporaryDirectory(prefix="fastvideo_template_frame_") as tmp:
        output = Path(tmp) / "frame.jpg"
        cmd = [
            settings.ffmpeg_binary,
            "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", source_path,
            "-frames:v", "1",
            "-vf", "scale=1280:-2",
            "-q:v", "3",
            str(output),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=90)
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 ffmpeg，请安装 FFmpeg。") from exc
        if proc.returncode != 0 or not output.exists():
            detail = proc.stderr.decode(errors="replace")[-500:]
            raise RuntimeError(f"关键帧提取失败：{detail}")
        return output.read_bytes()


def _delete_asset(db: Session, asset_id: str | None, project_id: str) -> None:
    if not asset_id:
        return
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        return
    if asset.file_key:
        try:
            storage.delete(asset.file_key)
        except Exception:
            logger.warning("template_frame_delete_failed", asset_id=asset_id)
    db.delete(asset)


def clone_template_reference_assets(
    db: Session,
    *,
    project_id: str,
    template_id: str,
    reference_asset_ids: list[str],
    reference_times: list[float] | None = None,
) -> list[str]:
    """把草稿关键帧复制为模板自有素材，避免草稿重提帧后模板引用失效。"""
    cloned_ids: list[str] = []
    times = list(reference_times or [])
    for index, asset_id in enumerate(reference_asset_ids):
        source = db.get(Asset, asset_id)
        if not source or source.project_id != project_id or not source.file_key:
            raise ValueError(f"第 {index + 1} 张模板参考帧不存在，请重新提取关键帧")
        data = storage.load(source.file_key)
        if not data:
            raise ValueError(f"第 {index + 1} 张模板参考帧文件为空，请重新提取关键帧")
        suffix = Path(source.file_key).suffix.lower() or ".jpg"
        key = (
            f"projects/{project_id}/video-templates/{template_id}/"
            f"reference_{index + 1}_{uuid4().hex}{suffix}"
        )
        storage.save(key, data)
        relative_time = 0.0 if index == 0 else (
            float(times[index - 1]) if index - 1 < len(times) else None
        )
        clone = Asset(
            project_id=project_id,
            name=f"{source.name or '模板参考帧'}-模板副本{index + 1}",
            asset_type="image",
            source="video_template_reference",
            file_key=key,
            file_size=len(data),
            mime_type=source.mime_type or "image/jpeg",
            width=source.width,
            height=source.height,
            aspect_ratio=source.aspect_ratio,
            is_original_model_shot=source.is_original_model_shot,
            is_ai_generated=False,
            meta={
                **(source.meta or {}),
                "template_id": template_id,
                "template_reference_index": index,
                "relative_time_seconds": relative_time,
            },
            tags=list(dict.fromkeys([*(source.tags or []), "视频模板", "模板参考帧"])),
        )
        db.add(clone)
        db.flush()
        cloned_ids.append(clone.id)
    return cloned_ids


def extract_template_frames(
    db: Session,
    draft: VideoTemplateDraft,
    *,
    clip_start: float,
    clip_end: float,
    middle: float | list[float] | None,
) -> dict[str, Any]:
    source = db.get(Asset, draft.source_video_asset_id)
    if not source or source.project_id != draft.project_id:
        raise ValueError("模板来源视频不存在")
    info = inspect_source_video(db, source)
    clip_start, clip_end = _validate_clip_times(
        float(info["duration_seconds"]), clip_start, clip_end
    )
    reference_times = _normalize_reference_times(clip_start, clip_end, middle)
    clip_length = clip_end - clip_start
    legacy_middle = next(
        (value for value in reference_times if value < clip_end - 0.001),
        round(clip_start + clip_length / 2, 3),
    )
    source_path = storage.local_path(source.file_key or "")
    old_ids = [
        draft.first_frame_asset_id,
        draft.middle_frame_asset_id,
        draft.last_frame_asset_id,
        *(draft.reference_frame_asset_ids or []),
    ]
    try:
        frame_bytes_by_time = {
            clip_start: _extract_frame(source_path, clip_start),
            legacy_middle: _extract_frame(source_path, legacy_middle),
            clip_end: _extract_frame(source_path, clip_end),
        }
        for timestamp in reference_times:
            if timestamp not in frame_bytes_by_time:
                frame_bytes_by_time[timestamp] = _extract_frame(source_path, timestamp)
    finally:
        storage.release_local_path(source_path)

    for old_id in old_ids:
        _delete_asset(db, old_id, draft.project_id)

    frame_ids: dict[str, str] = {}

    def create_frame_asset(role: str, data: bytes, timestamp: float) -> str:
        key = f"projects/{draft.project_id}/template-drafts/{draft.id}/{role}_{uuid4().hex}.jpg"
        storage.save(key, data)
        media = probe_media(data, suffix=".jpg")
        asset = Asset(
            project_id=draft.project_id,
            name=f"{draft.name}-{role}帧",
            asset_type="image",
            source="video_template_frame",
            file_key=key,
            file_size=len(data),
            mime_type="image/jpeg",
            width=media.get("width"),
            height=media.get("height"),
            is_original_model_shot=False,
            is_ai_generated=False,
            meta={
                "template_draft_id": draft.id,
                "frame_role": role,
                "timestamp_seconds": timestamp,
            },
            tags=["视频模板", f"{role}帧"],
        )
        db.add(asset)
        db.flush()
        return asset.id

    frame_ids["first"] = create_frame_asset("first", frame_bytes_by_time[clip_start], clip_start)
    frame_ids["middle"] = create_frame_asset("middle", frame_bytes_by_time[legacy_middle], legacy_middle)
    frame_ids["last"] = create_frame_asset("last", frame_bytes_by_time[clip_end], clip_end)

    extra_ids: dict[float, str] = {}
    for index, timestamp in enumerate(reference_times, start=1):
        if abs(timestamp - clip_end) < 0.001:
            extra_ids[timestamp] = frame_ids["last"]
        elif abs(timestamp - legacy_middle) < 0.001:
            extra_ids[timestamp] = frame_ids["middle"]
        else:
            extra_ids[timestamp] = create_frame_asset(
                f"reference_{index}", frame_bytes_by_time[timestamp], timestamp
            )

    reference_ids = [frame_ids["first"]] + [extra_ids[timestamp] for timestamp in reference_times]
    reference_ids = list(dict.fromkeys(reference_ids))

    draft.clip_start_seconds = clip_start
    draft.clip_end_seconds = clip_end
    draft.middle_seconds = legacy_middle
    draft.first_frame_asset_id = frame_ids["first"]
    draft.middle_frame_asset_id = frame_ids["middle"]
    draft.last_frame_asset_id = frame_ids["last"]
    draft.reference_frame_asset_ids = reference_ids
    draft.reference_frame_times = reference_times
    draft.status = "frames_ready"
    draft.analysis_warnings = []
    db.commit()
    db.refresh(draft)
    return {
        "info": info,
        "clip_start": clip_start,
        "clip_end": clip_end,
        "middle": legacy_middle,
        "reference_times": reference_times,
        "reference_asset_ids": reference_ids,
    }
