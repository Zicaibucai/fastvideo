"""配音编排服务（VoiceService）。

职责：
- 单条/批量配音生成（估算 → 规范化 → 合成 → 质量检查 → 波形 → 字幕 → 版本）
- 时长智能适配（matched / slightly_short / slightly_long / script_adjustment_required）
- 音频版本管理（选择/恢复/软删除）
- 解说词变化追踪（标记 stale，不删除历史版本）
- 项目级 SRT / WAV / MP3 导出
- 授权检查（正式导出必须检查音色授权状态）

原则：
- 不得在未经授权情况下克隆真人声音（adapter 层不提供克隆能力）
- Mock 音频明确标记 is_mock，不冒充真实 AI 语音
- 为匹配时长不得生成明显失真的高速语音（速度钳制在合理范围）
- 历史音频版本不被新生成结果覆盖
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.factory import get_tts_adapter
from app.adapters.tts import CapabilityError
from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.audio_version import AudioVersion
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.voice_template import VoiceTemplate
from app.services.audio_utils import (
    analyze_audio,
    any_audio_to_wav,
    build_subtitles,
    compute_waveform,
    estimate_duration_seconds,
    render_srt,
)
from app.services.narration_normalizer import normalize_narration
from app.services.pronunciation_service import get_effective_rules

logger = get_logger(__name__)

# 默认合理语速范围
SPEED_MIN = 0.85
SPEED_MAX = 1.20

# 授权状态不允许用于正式导出
FORBIDDEN_AUTH_STATUSES = {"unknown", "pending", "rejected", "expired"}

TARGET_LUFS = -16.0
TRUE_PEAK_DB = -1.5

# 每个版本估算成本（Mock 为 0，真实 Provider 按字数估算）
ESTIMATED_COST_PER_CHAR = 0.0004  # 元/字（真实 Provider 参考价）
MOCK_COST = 0.0


class VoiceError(Exception):
    """配音业务异常。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def narration_hash(narration: str | None) -> str:
    return hashlib.sha256((narration or "").encode("utf-8")).hexdigest()


# ============================================================
# 授权
# ============================================================

def ensure_template_authorized(template: VoiceTemplate, *, for_export: bool = False) -> None:
    """检查模板授权。

    for_export=True 时：unknown/pending/rejected/expired 不得用于正式导出。
    mock_only 只能用于演示。
    """
    status = template.authorization_status
    if status == "mock_only":
        if for_export:
            raise VoiceError("该音色为演示（mock_only）授权，不得用于正式视频导出。")
        return
    if for_export and status in FORBIDDEN_AUTH_STATUSES:
        raise VoiceError(f"该音色授权状态为「{status}」，不得用于正式视频导出，请选择已授权音色。")


# ============================================================
# 估算
# ============================================================

def estimate_for_shot(
    db: Session,
    project_id: str,
    shot_id: str,
    voice_template_id: str | None,
) -> dict[str, Any]:
    """生成配音前的时长估算（不实际生成）。"""
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise VoiceError("分镜不存在")

    template = _resolve_template(db, project_id, voice_template_id)
    text = shot.narration or ""
    speed = template.speed if template else 1.0
    pause = template.pause_strength if template else 1.0

    rules = get_effective_rules(db, project_id)
    norm = normalize_narration(text, rules)

    estimated = estimate_duration_seconds(text, speed=speed, pause_strength=pause)
    target = shot.duration_seconds or estimated
    diff = target - estimated
    ratio = (diff / target) if target else 0.0

    if abs(ratio) <= 0.05:
        suggestion = "预计时长与目标时长基本匹配，可直接生成。"
    elif ratio < 0:
        suggestion = f"预计比目标快 {-ratio * 100:.1f}%，可适当放慢语速（建议 {_clamp_speed(speed * 1.1)}）或增加停顿。"
    else:
        suggestion = f"预计比目标慢 {ratio * 100:.1f}%，可适当加快语速（建议 {_clamp_speed(speed * 0.9)}）。"

    # 字数
    char_count = len(text.replace(" ", ""))
    effective_chars = sum(
        1.0 if not (ch.isascii() and ch.isalnum()) else 0.6
        for ch in norm.normalized_text
        if ch.strip() and ch not in "，。！？；：、,.!?;"
    )

    return {
        "shot_id": shot_id,
        "narration": text,
        "normalized_text": norm.normalized_text,
        "pronunciation_snapshot": norm.pronunciation_snapshot,
        "warnings": norm.warnings,
        "char_count": char_count,
        "effective_chars": round(effective_chars, 1),
        "target_duration_seconds": round(target, 3),
        "estimated_duration_seconds": round(estimated, 3),
        "duration_difference": round(diff, 3),
        "duration_difference_ratio": round(ratio, 4),
        "suggestion": suggestion,
        "recommended_speed_min": SPEED_MIN,
        "recommended_speed_max": SPEED_MAX,
        "template": {
            "id": template.id if template else None,
            "name": template.name if template else None,
            "speed": speed,
            "pause_strength": pause,
            "speaking_style": template.effective_speaking_style if template else "正式稳重",
            "is_mock": template is not None and template.voice_provider in ("mock", "disabled"),
        } if template else None,
    }


# ============================================================
# 模板解析
# ============================================================

def _resolve_template(db: Session, project_id: str, voice_template_id: str | None) -> VoiceTemplate | None:
    if not voice_template_id:
        return None
    tpl = db.get(VoiceTemplate, voice_template_id)
    if not tpl:
        raise VoiceError("配音模板不存在")
    if not tpl.is_enabled:
        raise VoiceError("该配音模板已停用")
    if tpl.project_id and tpl.project_id != project_id:
        raise VoiceError("无权使用该配音模板")
    return tpl


def _template_to_snapshot(template: VoiceTemplate | None) -> dict[str, Any]:
    if not template:
        return {
            "voice_template_id": None,
            "provider": "default",
            "voice_id": settings.ai_tts_voice,
            "authorization_status": "mock_only",
            "authorization_type": "mock",
        }
    return {
        "voice_template_id": template.id,
        "provider": template.voice_provider,
        "voice_id": template.effective_voice_id,
        "model_name": template.model_name,
        "speed": template.speed,
        "pitch": template.pitch,
        "volume": template.volume,
        "pause_strength": template.pause_strength,
        "speaking_style": template.effective_speaking_style,
        "authorization_status": template.authorization_status,
        "authorization_type": template.authorization_type,
        "authorization_note": template.authorization_note,
    }


# ============================================================
# 单条生成
# ============================================================

def generate_voice_version(
    db: Session,
    *,
    project_id: str,
    shot_id: str,
    voice_template_id: str | None,
    user_name: str | None = None,
    speed_override: float | None = None,
    pitch_override: float | None = None,
    volume_override: float | None = None,
    emotion_override: str | None = None,
    pause_override: float | None = None,
    normalized_text_override: str | None = None,
    seed: int | None = None,
    output_formats: list[str] | None = None,
    idempotency_key: str | None = None,
    create_assets: bool = True,
) -> AudioVersion:
    """为单个分镜生成一个新配音版本（V1 起递增，不覆盖历史版本）。"""
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise VoiceError("分镜不存在")
    text = shot.narration or ""
    if not text.strip():
        raise VoiceError("分镜解说词为空，无法生成配音。")

    template = _resolve_template(db, project_id, voice_template_id)

    # 幂等键：已存在相同 key 的版本直接返回
    if idempotency_key:
        existing = (
            db.query(AudioVersion)
            .filter(
                AudioVersion.project_id == project_id,
                AudioVersion.storyboard_shot_id == shot_id,
                AudioVersion.provider_metadata is not None,
            )
            .all()
        )
        for v in existing:
            meta = v.provider_metadata or {}
            if meta.get("idempotency_key") == idempotency_key:
                return v

    # 规范化朗读文本
    rules = get_effective_rules(db, project_id)
    norm = normalize_narration(text, rules)
    normalized_text = normalized_text_override or norm.normalized_text
    if not normalized_text.strip():
        raise VoiceError("朗读文本为空，无法生成配音。")

    # 参数
    speed = _clamp_speed(speed_override if speed_override is not None else (template.speed if template else 1.0))
    pause = pause_override if pause_override is not None else (template.pause_strength if template else 1.0)
    pitch = pitch_override if pitch_override is not None else (template.pitch if template else 1.0)
    volume = volume_override if volume_override is not None else (template.volume if template else 1.0)
    emotion = emotion_override if emotion_override is not None else (template.emotion if template else None)

    target = shot.duration_seconds or estimate_duration_seconds(text, speed=speed, pause_strength=pause)
    estimated = estimate_duration_seconds(text, speed=speed, pause_strength=pause)

    # 调用 Adapter
    adapter = get_tts_adapter()
    if not adapter.is_available():
        raise VoiceError("TTS 服务不可用，请检查 API Key 配置。")

    is_mock = adapter.provider == "mock"

    # Provider 不支持参数必须报错，不得静默忽略
    wav_bytes = None
    mp3_bytes = None
    try:
        raw = adapter.synthesize(
            normalized_text,
            voice=template.effective_voice_id if template else None,
            speed=speed,
            format="wav",
            pitch=pitch if pitch != 1.0 else None,
            volume=volume if volume != 1.0 else None,
            emotion=emotion,
            seed=seed,
            pause_strength=pause,
        )
        wav_bytes = any_audio_to_wav(raw)
        # 统一导出 MP3
        if output_formats is None or "mp3" in output_formats:
            from app.adapters.tts import wav_to_mp3

            mp3_bytes = wav_to_mp3(wav_bytes, bitrate=settings.tts_mp3_bitrate)
    except CapabilityError as exc:
        raise VoiceError(str(exc))
    except Exception as exc:
        logger.exception("tts_synthesize_failed", shot_id=shot_id)
        raise VoiceError(adapter.normalize_error(exc))

    # 质量检查
    quality = analyze_audio(wav_bytes, is_mock=is_mock)
    actual_duration = float(quality.get("duration_seconds") or 0)

    # 波形
    waveform = compute_waveform(wav_bytes)

    # 字幕
    subtitles = build_subtitles(
        text,
        normalized_text=normalized_text,
        total_duration=actual_duration,
        timing_source="estimated" if not adapter.supports("sentence_timestamps") else "provider",
        pause_strength=pause,
    )

    # 保存素材
    wav_asset_id = None
    mp3_asset_id = None
    audio_asset_id = None
    if create_assets:
        key_root = f"projects/{project_id}/shots/{shot_id}/voice/{uuid4().hex}"
        if wav_bytes:
            wav_asset_id, audio_asset_id = _save_audio_asset(
                db, project_id, shot, wav_bytes, key_root + ".wav", "audio/wav",
                is_mock, speed, "wav", template, seed,
            )
        if mp3_bytes:
            mp3_asset_id, _ = _save_audio_asset(
                db, project_id, shot, mp3_bytes, key_root + ".mp3", "audio/mpeg",
                is_mock, speed, "mp3", template, seed,
            )
            audio_asset_id = audio_asset_id or mp3_asset_id

    # 版本号
    max_ver = db.query(AudioVersion).filter(
        AudioVersion.storyboard_shot_id == shot_id,
        AudioVersion.is_deleted.is_(False),
    ).count()
    version_number = max_ver + 1

    # 时长适配状态
    duration_status, diff, ratio = _classify_duration(target, actual_duration)

    version = AudioVersion(
        project_id=project_id,
        storyboard_shot_id=shot_id,
        voice_template_id=template.id if template else None,
        version_number=version_number,
        original_text_snapshot=text,
        normalized_text_snapshot=normalized_text,
        pronunciation_snapshot=norm.pronunciation_snapshot,
        narration_hash=narration_hash(text),
        provider=adapter.provider,
        model_name=template.model_name if template else settings.ai_tts_model,
        voice_id=template.effective_voice_id if template else settings.ai_tts_voice,
        speed=speed,
        pitch=pitch,
        volume=volume,
        emotion=emotion,
        pause_strength=pause,
        seed=seed,
        target_duration_seconds=round(target, 3),
        estimated_duration_seconds=round(estimated, 3),
        actual_duration_seconds=round(actual_duration, 3),
        duration_difference=round(diff, 3),
        duration_difference_ratio=round(ratio, 4),
        duration_status=duration_status,
        audio_asset_id=audio_asset_id,
        wav_asset_id=wav_asset_id,
        mp3_asset_id=mp3_asset_id,
        subtitle_data=subtitles,
        waveform_data=waveform,
        provider_metadata={
            "idempotency_key": idempotency_key,
            "seed": seed,
            "estimated_cost": _estimate_cost(adapter.provider, normalized_text),
            "is_mock": is_mock,
        },
        quality_metrics=quality,
        quality_status=quality["quality_status"],
        authorization_snapshot=_template_to_snapshot(template),
        is_mock=is_mock,
        estimated_cost=_estimate_cost(adapter.provider, normalized_text),
        currency="CNY",
    )
    db.add(version)
    db.flush()

    # 首个版本自动设为正式（后续版本由用户选择）
    selected_count = db.query(AudioVersion).filter(
        AudioVersion.storyboard_shot_id == shot_id,
        AudioVersion.is_selected.is_(True),
        AudioVersion.is_deleted.is_(False),
    ).count()
    if version_number == 1 or selected_count == 0:
        _apply_selection(db, shot, version, user_name or "system")

    # 更新分镜解说词哈希（若未记录）
    if not shot.narration_hash:
        shot.narration_hash = narration_hash(text)

    db.commit()
    db.refresh(version)
    return version


def _classify_duration(target: float, actual: float) -> tuple[str, float, float]:
    """时长适配规则（九.1-3）。"""
    if target <= 0:
        return "matched", 0.0, 0.0
    diff = actual - target
    ratio = abs(diff) / target
    if ratio <= 0.05:
        status = "matched"
    elif ratio <= 0.12:
        status = "slightly_long" if diff > 0 else "slightly_short"
    else:
        status = "script_adjustment_required"
    return status, round(diff, 3), round(ratio, 4)


def _estimate_cost(provider: str, text: str) -> float:
    if provider in ("mock", "disabled", ""):
        return MOCK_COST
    return round(len(text) * ESTIMATED_COST_PER_CHAR, 4)


def _save_audio_asset(
    db: Session,
    project_id: str,
    shot: StoryboardShot,
    data: bytes,
    file_key: str,
    mime_type: str,
    is_mock: bool,
    speed: float,
    fmt: str,
    template: VoiceTemplate | None,
    seed: int | None,
) -> tuple[str, str]:
    storage.save(file_key, data)
    asset = Asset(
        project_id=project_id,
        name=f"分镜{shot.sequence} 配音V{fmt}",
        asset_type="audio",
        source="ai_tts",
        file_key=file_key,
        file_size=len(data),
        mime_type=mime_type,
        is_ai_generated=True,
        is_conceptual=False,
        ai_disclaimer=(
            "Mock Audio：演示合成音，非真人语音。" if is_mock
            else "AI 合成语音，音色已按授权使用。"
        ),
        generated_by="tts_adapter",
        prompt=shot.narration or "",
        meta={"voice": template.effective_voice_id if template else settings.ai_tts_voice,
              "speed": speed, "format": fmt, "seed": seed, "is_mock": is_mock},
    )
    db.add(asset)
    db.flush()
    return asset.id, asset.id


def _apply_selection(db: Session, shot: StoryboardShot, version: AudioVersion, user_name: str) -> None:
    """把某版本设为该分镜的正式配音。"""
    # 取消同分镜其他版本选择
    db.query(AudioVersion).filter(
        AudioVersion.storyboard_shot_id == shot.id,
        AudioVersion.is_selected.is_(True),
    ).update({"is_selected": False})

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    version.is_selected = True
    version.selected_by = user_name
    version.selected_at = now

    # 更新分镜音频引用（优先 MP3，浏览器可播放）
    shot.audio_asset_id = version.mp3_asset_id or version.wav_asset_id or version.audio_asset_id
    shot.tts_voice_id = version.voice_id
    shot.status = "edited"

    # 标记相关视频分段需要重建
    from app.services.render_service import _mark_video_segments_rebuild

    _mark_video_segments_rebuild(db, shot.project_id, shot.id, reason="分镜正式配音已更换")


# ============================================================
# 版本管理
# ============================================================

def list_versions_for_shot(db: Session, project_id: str, shot_id: str) -> list[AudioVersion]:
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise VoiceError("分镜不存在")
    return (
        db.query(AudioVersion)
        .filter(
            AudioVersion.storyboard_shot_id == shot_id,
            AudioVersion.is_deleted.is_(False),
        )
        .order_by(AudioVersion.version_number.asc())
        .all()
    )


def select_voice_version(
    db: Session,
    project_id: str,
    shot_id: str,
    version_id: str,
    user_name: str,
) -> dict[str, Any]:
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise VoiceError("分镜不存在")
    version = db.get(AudioVersion, version_id)
    if not version or version.project_id != project_id or version.storyboard_shot_id != shot_id:
        raise VoiceError("配音版本不存在")
    if version.is_deleted:
        raise VoiceError("配音版本已删除")
    if version.quality_status == "failed":
        raise VoiceError("质量检查未通过（failed）的版本不能设为正式分镜配音")
    _apply_selection(db, shot, version, user_name)
    db.commit()
    db.refresh(version)
    return {
        "version_id": version.id,
        "version_number": version.version_number,
        "audio_asset_id": shot.audio_asset_id,
        "selected_by": version.selected_by,
        "selected_at": version.selected_at,
    }


def restore_voice_version(
    db: Session,
    project_id: str,
    shot_id: str,
    version_id: str,
    user_name: str,
) -> dict[str, Any]:
    """恢复历史选择（不复制文件，仅重新选择）。"""
    return select_voice_version(db, project_id, shot_id, version_id, user_name)


def soft_delete_voice_version(
    db: Session,
    project_id: str,
    shot_id: str,
    version_id: str,
    user_name: str,
) -> None:
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise VoiceError("分镜不存在")
    version = db.get(AudioVersion, version_id)
    if not version or version.project_id != project_id or version.storyboard_shot_id != shot_id:
        raise VoiceError("配音版本不存在")
    if version.is_selected:
        raise VoiceError("该版本是当前正式配音，不能删除；请先选择其他正式版本。")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    version.is_deleted = True
    version.deleted_by = user_name
    version.deleted_at = now
    db.commit()


# ============================================================
# 解说词变化追踪
# ============================================================

def mark_shot_narration_changed(
    db: Session,
    shot: StoryboardShot,
    old_narration: str | None,
    new_narration: str | None,
) -> None:
    """解说词修改后：标记旧配音与字幕为 stale，不删除历史版本。"""
    new_hash = narration_hash(new_narration)
    old_hash = narration_hash(old_narration)

    if new_hash == old_hash:
        return

    shot.narration_prev_hash = old_hash or shot.narration_hash
    shot.narration_hash = new_hash
    shot.narration_updated_at = time.strftime("%Y-%m-%d %H:%M:%S")

    versions = (
        db.query(AudioVersion)
        .filter(
            AudioVersion.storyboard_shot_id == shot.id,
            AudioVersion.is_deleted.is_(False),
        )
        .all()
    )
    for v in versions:
        if v.narration_hash != new_hash:
            v.is_stale = True
            v.stale_reason = "解说词已修改，需要重新生成配音"


def find_reusable_versions(db: Session, project_id: str, shot_id: str) -> list[AudioVersion]:
    """解说词恢复到原版本时，检测可复用的历史音频。"""
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        return []
    current_hash = shot.narration_hash
    if not current_hash:
        return []
    return (
        db.query(AudioVersion)
        .filter(
            AudioVersion.storyboard_shot_id == shot_id,
            AudioVersion.is_deleted.is_(False),
            AudioVersion.narration_hash == current_hash,
        )
        .order_by(AudioVersion.version_number.asc())
        .all()
    )


# ============================================================
# 导出
# ============================================================

def _selected_version(db: Session, project_id: str, shot_id: str) -> AudioVersion | None:
    return (
        db.query(AudioVersion)
        .filter(
            AudioVersion.storyboard_shot_id == shot_id,
            AudioVersion.project_id == project_id,
            AudioVersion.is_selected.is_(True),
            AudioVersion.is_deleted.is_(False),
            AudioVersion.is_stale.is_(False),
        )
        .first()
    )


def export_project_srt(db: Session, project_id: str) -> bytes:
    """项目级 SRT：按分镜顺序累计（当前以分镜 durationSeconds 为基准，标为估算）。"""
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    all_subs: list[dict[str, Any]] = []
    offset_ms = 0
    for shot in shots:
        version = _selected_version(db, project_id, shot.id)
        if not version or not version.subtitle_data:
            continue
        for seg in version.subtitle_data:
            item = dict(seg)
            item["_shot_id"] = shot.id
            item["_sequence"] = shot.sequence
            all_subs.append(item)
        # 累计时间轴：当前以分镜 durationSeconds 为基准（估算）
        shot_dur_ms = int((shot.duration_seconds or 0) * 1000)
        offset_ms += shot_dur_ms
    # 重新编号 + 渲染
    from app.services.audio_utils import _srt_timecode, _wrap_subtitle

    lines: list[str] = []
    for idx, seg in enumerate(all_subs, start=1):
        start = seg.get("start_ms", 0)
        end = seg.get("end_ms", 0)
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_srt_timecode(start)} --> {_srt_timecode(end)}")
        lines.append(_wrap_subtitle(text))
        lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def export_voice_audio_zip(
    db: Session,
    project_id: str,
    fmt: str = "wav",
) -> tuple[bytes, str]:
    """导出全部正式配音为 zip（WAV 或 MP3）。"""
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for shot in shots:
            version = _selected_version(db, project_id, shot.id)
            if not version:
                continue
            asset_id = version.wav_asset_id if fmt == "wav" else version.mp3_asset_id
            if not asset_id:
                continue
            asset = db.get(Asset, asset_id)
            if not asset or not asset.file_key or asset_id in used:
                continue
            try:
                data = storage.load(asset.file_key)
            except Exception:
                continue
            used.add(asset_id)
            name = f"{shot.sequence:02d}_{_safe_name(shot.title or '分镜')}.{fmt}"
            zf.writestr(name, data)
    content = buf.getvalue()
    filename = f"项目配音_{fmt}.zip"
    return content, filename


def _safe_name(name: str) -> str:
    keep = [c for c in name if c.isalnum() or c in "_- "]
    return "".join(keep).strip()[:40] or "shot"


def project_voice_summary(db: Session, project_id: str) -> dict[str, Any]:
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    duration_status_counts: dict[str, int] = {}
    quality_status_counts: dict[str, int] = {}
    missing = 0
    stale = 0
    mock_count = 0
    total_actual = 0.0
    for shot in shots:
        versions = list_versions_for_shot(db, project_id, shot.id)
        selected = next((v for v in versions if v.is_selected), None)
        if not selected:
            missing += 1
            continue
        duration_status_counts[selected.duration_status] = duration_status_counts.get(selected.duration_status, 0) + 1
        quality_status_counts[selected.quality_status] = quality_status_counts.get(selected.quality_status, 0) + 1
        if selected.is_stale:
            stale += 1
        if selected.is_mock:
            mock_count += 1
        total_actual += selected.actual_duration_seconds or 0
    return {
        "shot_count": len(shots),
        "missing_voice_count": missing,
        "stale_count": stale,
        "mock_count": mock_count,
        "total_actual_duration_seconds": round(total_actual, 1),
        "duration_status_counts": duration_status_counts,
        "quality_status_counts": quality_status_counts,
    }


# ============================================================
# 工具
# ============================================================

def _clamp_speed(speed: float) -> float:
    """钳制语速在合理范围，禁止为匹配时长生成失真的高速语音。"""
    if speed is None:
        return 1.0
    return max(SPEED_MIN, min(SPEED_MAX, float(speed)))


def _default_params() -> dict[str, Any]:
    return {}


def prepare_shot_list_for_batch(
    db: Session,
    project_id: str,
    shot_ids: list[str] | None,
    *,
    skip_empty: bool,
    regenerate_stale: bool,
) -> list[StoryboardShot]:
    """批量生成前筛选分镜。"""
    query = db.query(StoryboardShot).filter(StoryboardShot.project_id == project_id)
    if shot_ids:
        query = query.filter(StoryboardShot.id.in_(shot_ids))
    shots = query.order_by(StoryboardShot.sequence.asc()).all()

    result = []
    for s in shots:
        if skip_empty and not (s.narration or "").strip():
            continue
        versions = list_versions_for_shot(db, project_id, s.id)
        selected = next((v for v in versions if v.is_selected), None)
        if selected and not selected.is_stale and not regenerate_stale:
            # 已通过审核的正式配音，不重新生成
            continue
        result.append(s)
    return result


def refresh_batch_progress(db: Session, parent_id: str) -> RenderTask:
    """聚合父任务（tts_batch）进度与状态。"""
    parent = db.get(RenderTask, parent_id)
    if not parent:
        raise VoiceError("批量任务不存在")
    children = db.query(RenderTask).filter(RenderTask.parent_task_id == parent_id).all()
    total = len(children)
    status_counts: dict[str, int] = {}
    for c in children:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1
    done = status_counts.get("success", 0)
    failed = status_counts.get("failed", 0)
    cancelled = status_counts.get("cancelled", 0)
    running = status_counts.get("running", 0) + status_counts.get("queued", 0)

    parent.result = {
        "total": total,
        "success": done,
        "failed": failed,
        "cancelled": cancelled,
        "running": running,
    }
    if total and done + failed + cancelled >= total:
        parent.status = "success" if done > 0 else "failed"
        parent.progress = 100
        parent.message = f"批量生成完成：成功 {done}，失败 {failed}"
    else:
        parent.status = "running"
        parent.progress = round((done + failed) / total * 100) if total else 0
        parent.message = f"批量生成中：{done}/{total}"
    db.commit()
    db.refresh(parent)
    return parent
