"""自定义合成服务：不绑定分镜，自选视频 + 自输字幕/TTS 直接合成单个片段。

与视频工程分段（render_segment）的区别：输入完全来自用户当次提交，
不依赖 StoryboardShot / AudioVersion；产出归档素材库（category=自定义合成），
供分镜拼接等功能继续选用。任务载体是 RenderTask（task_type=custom_segment_render）。
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.render_task import RenderTask
from app.services.audio_utils import estimate_duration_seconds
from app.services.video_composer import (
    build_ass,
    probe_media,
    render_video_segment,
)
from app.services.video_project_media import extract_audio
from app.services.video_project_service import (
    VideoProjectError,
    _persist_video_render_asset,
)

logger = get_logger(__name__)

MIN_DURATION = 1.5
MAX_DURATION = 60.0

# 句末标点切分；超长句再按逗号/顿号切
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")
_CLAUSE_SPLIT = re.compile(r"(?<=[，,、])")
MAX_LINE_CHARS = 28


def split_subtitle_lines(text: str) -> list[str]:
    """把用户输入的字幕文本切成适合逐条显示的短句。"""
    lines: list[str] = []
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        for sentence in _SENTENCE_SPLIT.split(raw_line):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= MAX_LINE_CHARS:
                lines.append(sentence)
                continue
            # 超长句按逗号/顿号续切，仍超长则硬切
            clause = ""
            for part in _CLAUSE_SPLIT.split(sentence):
                if clause and len(clause) + len(part) > MAX_LINE_CHARS:
                    lines.append(clause)
                    clause = part
                else:
                    clause += part
                while len(clause) > MAX_LINE_CHARS:
                    lines.append(clause[:MAX_LINE_CHARS])
                    clause = clause[MAX_LINE_CHARS:]
            if clause.strip():
                lines.append(clause.strip())
    return lines


def distribute_subtitles(lines: list[str], duration: float) -> list[dict[str, Any]]:
    """按每条字数加权均分分段时长，生成 build_ass 需要的定时字幕。"""
    if not lines:
        return []
    weights = [max(1, len(line)) for line in lines]
    total = sum(weights)
    start_ms = 0.0
    subtitles: list[dict[str, Any]] = []
    for line, weight in zip(lines, weights):
        span = duration * 1000 * weight / total
        end_ms = start_ms + span
        subtitles.append({
            "start_ms": round(start_ms),
            "end_ms": round(end_ms),
            "text": line,
        })
        start_ms = end_ms
    return subtitles


def _clamp(d: float) -> float:
    return round(max(MIN_DURATION, min(MAX_DURATION, d)), 3)


def _resolve_audio(
    db: Session,
    *,
    project_id: str,
    audio_mode: str,
    voice_template_id: str | None,
    subtitle_text: str,
    video_path: Path,
    tmp: Path,
    has_audio: bool,
) -> tuple[bytes | None, bool]:
    """解析配音：mute → None；keep_original → 提取原声；tts → 合成 WAV。

    返回 (audio_bytes, is_mock_tts)。
    """
    if audio_mode == "keep_original":
        if not has_audio:
            return None, False
        audio_path = tmp / "original.m4a"
        extract_audio(video_path, audio_path)
        if not audio_path.exists():
            return None, False
        return audio_path.read_bytes(), False
    if audio_mode != "tts":
        return None, False

    from app.adapters.factory import get_tts_adapter
    from app.services.narration_normalizer import normalize_narration
    from app.services.pronunciation_service import get_effective_rules
    from app.services.voice_service import (
        VoiceError,
        _resolve_template,
        ensure_template_authorized,
    )

    if not subtitle_text.strip():
        raise VideoProjectError("TTS 配音需要填写字幕/朗读文本")
    template = _resolve_template(db, project_id, voice_template_id)
    if not template:
        raise VideoProjectError("请选择配音模板")
    try:
        ensure_template_authorized(template, for_export=False)
    except VoiceError as exc:
        raise VideoProjectError(str(exc)) from None

    rules = get_effective_rules(db, project_id)
    normalized = normalize_narration(subtitle_text, rules).normalized_text
    if not normalized.strip():
        raise VideoProjectError("朗读文本为空，无法生成配音")

    adapter = get_tts_adapter()
    if not adapter.is_available():
        raise VideoProjectError("TTS 服务不可用，请检查 API Key 配置")
    wav = adapter.synthesize(
        normalized,
        voice=template.effective_voice_id,
        speed=template.speed,
        format="wav",
        pitch=template.pitch if template.pitch != 1.0 else None,
        volume=template.volume if template.volume != 1.0 else None,
        emotion=template.emotion,
    )
    return wav, adapter.provider == "mock"


def estimate_tts_duration(text: str, speed: float = 1.0, pause_strength: float = 1.0) -> float:
    """TTS 模式未显式给时长时的默认值：朗读估算 + 首尾停顿。"""
    return estimate_duration_seconds(text, speed=speed, pause_strength=pause_strength) + 0.8


def render_custom_segment(db: Session, task_id: str) -> dict[str, Any]:
    """执行自定义合成。任务状态由调用方（run_task / Celery 包装）管理。"""
    task = db.get(RenderTask, task_id)
    if not task:
        raise VideoProjectError("合成任务不存在")
    if task.status == "cancelled":
        return {"status": "cancelled"}
    params = task.params or {}

    def _progress(value: int, message: str) -> None:
        task.progress = value
        task.message = message
        db.commit()

    asset = db.get(Asset, params.get("visual_asset_id") or "")
    if not asset or asset.project_id != task.project_id:
        raise VideoProjectError("视频素材不存在")
    if asset.asset_type != "video" or not asset.file_key:
        raise VideoProjectError(f"素材「{asset.name}」不是视频文件")

    _progress(10, "读取视频素材…")
    video_bytes = storage.load(asset.file_key)
    info = probe_media(video_bytes, suffix=".mp4")
    if info.get("decodable") is False:
        raise VideoProjectError(f"素材「{asset.name}」不是可解码的视频，请重新上传")

    audio_mode = params.get("audio_mode") or "mute"
    subtitle_text = (params.get("subtitle_text") or "").strip()
    duration = params.get("duration")
    if duration is None:
        if audio_mode == "tts" and subtitle_text:
            duration = estimate_tts_duration(subtitle_text)
        else:
            duration = float(info.get("duration_seconds") or MIN_DURATION)
    duration = _clamp(float(duration))

    w = int(params.get("width") or 1920)
    h = int(params.get("height") or 1080)
    fps = int(params.get("fps") or 25)
    volume = float(params.get("volume") if params.get("volume") is not None else 1.0)

    with __import__("tempfile").TemporaryDirectory(prefix="fv_custom_") as td:
        tmp = Path(td)
        video_path = tmp / "src.mp4"
        video_path.write_bytes(video_bytes)

        ass_path = None
        if subtitle_text:
            lines = split_subtitle_lines(subtitle_text)
            subs = distribute_subtitles(lines, duration)
            if subs:
                ass_file = tmp / "sub.ass"
                ass_file.write_text(build_ass(subs, style=None, width=w, height=h), encoding="utf-8")
                ass_path = str(ass_file)

        _progress(30, "处理配音…")
        audio_bytes, is_mock_tts = _resolve_audio(
            db,
            project_id=task.project_id,
            audio_mode=audio_mode,
            voice_template_id=params.get("voice_template_id"),
            subtitle_text=subtitle_text,
            video_path=video_path,
            tmp=tmp,
            has_audio=bool(info.get("has_audio")),
        )

        _progress(50, "合成视频画面…")

        def _video_progress(value: int, message: str) -> None:
            task.progress = max(50, min(85, int(value)))
            task.message = message
            db.commit()

        try:
            data = render_video_segment(
                video_bytes,
                duration=duration,
                fit_mode=params.get("fit_mode") or "cover",
                width=w,
                height=h,
                fps=fps,
                audio_bytes=audio_bytes,
                volume=volume,
                short_video="loop",
                time_adaptation=params.get("time_adaptation") or "natural",
                ass_path=ass_path,
                progress_callback=_video_progress,
            )
        except Exception as exc:
            logger.exception("custom_segment_render_failed", task_id=task_id)
            raise VideoProjectError(f"自定义合成失败: {exc}") from exc

        _progress(90, "写入成片…")
        name = (params.get("name") or "").strip() or f"自定义合成·{time.strftime('%m%d-%H%M')}"
        out_key = f"projects/{task.project_id}/custom_segments/{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
        storage.save(out_key, data)
        render_asset = _persist_video_render_asset(
            db,
            project_id=task.project_id,
            name_prefix=name,
            owner_key=f"custom:{task.id}",
            storage_key=out_key,
            data=data,
            duration=duration,
            width=w,
            height=h,
            meta={
                "category": "自定义合成",
                "kind": "custom_segment",
                "custom_task_id": task.id,
                "source_asset_id": asset.id,
                "audio_mode": audio_mode,
                "is_mock_tts": is_mock_tts,
                "subtitle_line_count": len(split_subtitle_lines(subtitle_text)) if subtitle_text else 0,
                "time_adaptation": params.get("time_adaptation") or "natural",
            },
            tags=["自定义合成"],
        )
        db.commit()

    return {
        "status": "success",
        "asset_id": render_asset.id,
        "output_key": out_key,
        "output_url": f"/files/{out_key}",
        "duration": duration,
        "name": render_asset.name,
        "version": (render_asset.meta or {}).get("version"),
        "is_mock_tts": is_mock_tts,
    }
