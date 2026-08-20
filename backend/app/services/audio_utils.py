"""音频工具：时长估算、质量检查、波形、字幕切分与 SRT 导出。

- 时长估算：中文有效字符 + 英文单词 + 数字展开 + 标点停顿 + 语速/停顿强度
- 质量检查：可解码性、格式、采样率、声道、时长、静音占比、峰值、削波、响度（简化）
- 波形：固定采样点归一化峰值（不保存完整 PCM 到数据库）
- 字幕：按标点切句 + 时长按权重分配；SRT 导出（UTF-8）
"""

from __future__ import annotations

import array
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.narration_normalizer import normalize_narration

logger = get_logger(__name__)

# 中文标点停顿基准（秒）
_PAUSE_FULL = 0.35   # 。！？.!?
_PAUSE_MID = 0.18    # ，、,;
_PAUSE_LIGHT = 0.10  # 其他分隔
_START_BEEP = 0.12
_START_SILENCE = 0.08
_TRAIL_SILENCE = 0.15

# Mock 基准语速（字/秒）
_BASE_CHARS_PER_SECOND = 4.5

# 切句正则：中文标点 + ASCII !?;，ASCII . 仅在非数字夹持时切分（避免拆开小数点）
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；，、]|(?<![0-9])[.!?](?![0-9]))")


def text_weight(text: str) -> float:
    """中文按 1 字权重，ASCII 字母/数字按 0.6，标点与空白忽略。"""
    weight = 0.0
    for ch in text:
        if ch.isascii() and ch.isalnum():
            weight += 0.6
        elif ch.strip():
            weight += 1.0
    return weight


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p for p in parts if p.strip()]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ============================================================
# 时长估算
# ============================================================

def estimate_duration_seconds(
    text: str,
    *,
    speed: float = 1.0,
    pause_strength: float = 1.0,
) -> float:
    """估算朗读时长（秒）。

    与 Mock TTS 生成公式保持一致，使"预计时长"贴近"实际时长"。
    """
    if not text:
        return 0.0
    norm = normalize_narration(text).normalized_text
    sentences = split_sentences(norm) or [norm]
    cps = _BASE_CHARS_PER_SECOND * _clamp(speed, 0.5, 2.0)
    total = _START_BEEP + _START_SILENCE + _TRAIL_SILENCE
    for s in sentences:
        chars = text_weight(s)
        total += max(0.35, chars / cps)
        tail = s[-1] if s else ""
        if tail in "。！？.!?":
            pause = _PAUSE_FULL
        elif tail in "，、,;":
            pause = _PAUSE_MID
        else:
            pause = _PAUSE_LIGHT
        total += pause * _clamp(pause_strength, 0.3, 2.0)
    return round(total, 3)


# ============================================================
# 音频读取（ffprobe / ffmpeg 解码）
# ============================================================

def _write_temp(data: bytes, suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def ffprobe_info(data: bytes, suffix: str = ".wav") -> dict[str, Any]:
    """用 ffprobe 读取音频元信息。"""
    path = _write_temp(data, suffix)
    try:
        cmd = [
            settings.ffprobe_binary,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_name,sample_rate,channels",
            "-of", "json",
            path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return {"decodable": False, "error": proc.stderr[:300]}
        import json

        info = json.loads(proc.stdout or "{}")
        streams = info.get("streams", [])
        fmt = info.get("format", {})
        duration = None
        try:
            duration = float(fmt.get("duration") or 0)
        except (TypeError, ValueError):
            duration = None
        stream = streams[0] if streams else {}
        return {
            "decodable": True,
            "codec_name": stream.get("codec_name"),
            "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
            "channels": int(stream["channels"]) if stream.get("channels") else None,
            "duration_seconds": round(duration, 3) if duration else None,
        }
    except FileNotFoundError:
        logger.warning("ffprobe_not_found")
        return {"decodable": False, "error": "未找到 ffprobe"}
    except Exception as exc:
        return {"decodable": False, "error": str(exc)[:300]}
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass


def decode_to_pcm(data: bytes, suffix: str = ".wav") -> bytes:
    """用 ffmpeg 解码为 16-bit / 单声道 / 48kHz PCM。"""
    path = _write_temp(data, suffix)
    try:
        cmd = [
            settings.ffmpeg_binary,
            "-v", "error",
            "-i", path,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", "48000",
            "-ac", "1",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[:300])
        return proc.stdout
    except FileNotFoundError:
        raise RuntimeError("未找到 ffmpeg")
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass


def _samples_from_pcm(pcm: bytes) -> array.array:
    arr = array.array("h")
    # 本地字节序处理：ffmpeg 输出为小端
    if _is_little_endian():
        arr.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    else:
        raw = pcm[: len(pcm) - (len(pcm) % 2)]
        arr.frombytes(raw)
        arr.byteswap()
    return arr


def _is_little_endian() -> bool:
    import sys

    return sys.byteorder != "little"


# ============================================================
# 质量检查
# ============================================================

def analyze_audio(data: bytes, *, is_mock: bool = False) -> dict[str, Any]:
    """音频质量检查。

    简化检查：可解码性、格式、采样率、声道、时长、静音占比、峰值、削波、平均响度。
    不声称完整广播级响度检测（标注 simplified）。
    """
    info = ffprobe_info(data, suffix=".mp3" if _looks_mp3(data) else ".wav")
    if not info.get("decodable"):
        return {
            "quality_status": "failed",
            "decodable": False,
            "error": info.get("error", "无法解码"),
            "file_size": len(data),
            "is_mock": is_mock,
            "loudness_method": "simplified",
        }

    file_size = len(data)
    peak = 0.0
    rms = 0.0
    silent_ratio = 0.0
    clipping_ratio = 0.0
    samples: array.array = array.array("h")
    try:
        pcm = decode_to_pcm(data, suffix=".mp3" if _looks_mp3(data) else ".wav")
        samples = _samples_from_pcm(pcm)
    except Exception:
        samples = array.array("h")

    if samples:
        n = len(samples)
        nz = 0
        clipped = 0
        sum_sq = 0.0
        max_abs = 0
        for v in samples:
            av = abs(v)
            if av > 200:  # 静音阈值
                nz += 1
            if av >= 32760:
                clipped += 1
            if av > max_abs:
                max_abs = av
            sum_sq += v * v
        peak = max_abs / 32767.0
        rms = math.sqrt(sum_sq / n) / 32767.0 if n else 0.0
        silent_ratio = 1 - (nz / n)
        clipping_ratio = clipped / n

    # 简化响度（峰值归一化后 RMS 估算，非广播级）
    loudness_db = 20 * math.log10(max(rms, 1e-6)) if rms > 0 else -96.0

    warnings: list[str] = []
    status = "passed"
    duration = info.get("duration_seconds") or 0
    if duration <= 0 or silent_ratio > 0.98:
        status = "failed"
        warnings.append("音频为空或几乎全静音")
    if peak < 0.01 and status == "passed":
        warnings.append("音量过低")
        status = "warning"
    if clipping_ratio > 0.001:
        warnings.append(f"检测到削波（{clipping_ratio:.2%}）")
        status = "warning"
    if silent_ratio > 0.6:
        warnings.append(f"静音占比偏高（{silent_ratio:.1%}）")
        status = "warning"

    return {
        "quality_status": status,
        "decodable": True,
        "format": info.get("codec_name"),
        "sample_rate": info.get("sample_rate"),
        "channels": info.get("channels"),
        "duration_seconds": duration,
        "file_size": file_size,
        "peak": round(peak, 4),
        "rms": round(rms, 5),
        "loudness_db": round(loudness_db, 1),
        "loudness_method": "simplified",
        "silent_ratio": round(silent_ratio, 4),
        "clipping_ratio": round(clipping_ratio, 6),
        "warnings": warnings,
        "is_mock": is_mock,
        "target_lufs_note": "语音目标约 -16 LUFS，True Peak 不高于 -1.5 dB；此处为简化峰值检查，不构成完整响度检测。",
    }


def _looks_mp3(data: bytes) -> bool:
    return data[:3] == b"ID3" or (data[:2] == b"\xff\xfb") or (data[:2] == b"\xff\xf3")


def pcm_to_wav(pcm: bytes, sample_rate: int = 48000, channels: int = 1) -> bytes:
    """PCM(16-bit 小端) → WAV 容器。"""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def any_audio_to_wav(data: bytes, suffix: str | None = None) -> bytes:
    """任意音频（WAV/MP3 等）转 WAV（48kHz/单声道/16-bit）。"""
    return pcm_to_wav(decode_to_pcm(data, suffix=suffix or (".mp3" if _looks_mp3(data) else ".wav")))


# ============================================================
# 波形数据
# ============================================================

def compute_waveform(data: bytes, points: int = 200) -> dict[str, Any]:
    """生成轻量波形 JSON：固定数量采样点，保存归一化峰值。"""
    try:
        pcm = decode_to_pcm(data, suffix=".mp3" if _looks_mp3(data) else ".wav")
        samples = _samples_from_pcm(pcm)
    except Exception:
        return {"points": [0.0] * min(points, 200), "count": points, "error": "无法解码"}

    if not samples:
        return {"points": [0.0] * min(points, 200), "count": points}

    n = len(samples)
    bucket = max(1, n // points)
    out: list[float] = []
    for i in range(0, n, bucket):
        block = samples[i : i + bucket]
        peak = max((abs(v) for v in block), default=0) / 32767.0
        out.append(round(min(peak, 1.0), 4))
        if len(out) >= points:
            break
    while len(out) < points:
        out.append(0.0)
    return {"points": out, "count": len(out), "source": "peak_amplitude"}


# ============================================================
# 字幕
# ============================================================

def build_subtitles(
    text: str,
    *,
    normalized_text: str | None = None,
    total_duration: float,
    timing_source: str = "estimated",
    pause_strength: float = 1.0,
) -> list[dict[str, Any]]:
    """按标点切句，按权重分配时长，生成字幕句段。

    规则：
    - 字幕结束时间不超过音频时长
    - 不拆开日期/数字/单位/企业名称（按标点切句天然保持完整）
    - 字幕文字默认使用原始解说词
    """
    sentences = split_sentences(text) or ([text] if text.strip() else [])
    if not sentences:
        return []
    norm_sentences = split_sentences(normalized_text) if normalized_text else []

    # 每句权重 = 文本权重 + 停顿权重
    weights: list[float] = []
    for i, s in enumerate(sentences):
        w = max(0.35, text_weight(s))
        tail = s[-1] if s else ""
        if tail in "。！？.!?":
            pause = _PAUSE_FULL
        elif tail in "，、,;":
            pause = _PAUSE_MID
        else:
            pause = _PAUSE_LIGHT
        weights.append(w + pause * _clamp(pause_strength, 0.3, 2.0))
    total_w = sum(weights) or 1.0

    segs: list[dict[str, Any]] = []
    cursor = 0.0
    usable = max(0.0, total_duration)
    for i, s in enumerate(sentences):
        seg_dur = usable * weights[i] / total_w
        start = cursor
        end = min(usable, cursor + seg_dur)
        if end - start < 0.05 and i < len(sentences) - 1:
            # 太短的片段合并到下一句（避免单个标点独占一行）
            continue
        segs.append(
            {
                "sequence": len(segs) + 1,
                "start_ms": round(start * 1000),
                "end_ms": round(end * 1000),
                "text": s.strip(),
                "normalized_text": (norm_sentences[i].strip() if i < len(norm_sentences) else None),
                "timing_source": timing_source,
                "confidence": 0.9 if timing_source == "estimated" else 1.0,
            }
        )
        cursor = end
    if segs:
        segs[-1]["end_ms"] = round(usable * 1000)
    return segs


def _srt_timecode(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms2 = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms2:03d}"


def _wrap_subtitle(text: str, max_chars: int = 20) -> str:
    """把超长字幕拆为最多两行（不拆开中文词/数字/单位）。"""
    if len(text) <= max_chars:
        return text
    # 在标点或空格处寻找断点
    candidates = [m.start() for m in re.finditer(r"[，。！？、；,\s]", text)]
    mid = len(text) // 2
    cut = min(candidates, key=lambda c: abs(c - mid)) if candidates else -1
    if cut <= 0 or cut >= len(text) - 1:
        return text
    first = text[: cut + 1].strip()
    second = text[cut + 1 :].strip()
    if len(first) > 40 or len(second) > 40:
        return text
    return f"{first}\n{second}"


def render_srt(subtitles: list[dict[str, Any]], offset_ms: int = 0) -> str:
    """渲染 SRT（UTF-8 无 BOM）。"""
    lines: list[str] = []
    for idx, seg in enumerate(subtitles, start=1):
        start = seg.get("start_ms", 0) + offset_ms
        end = seg.get("end_ms", 0) + offset_ms
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_srt_timecode(start)} --> {_srt_timecode(end)}")
        lines.append(_wrap_subtitle(text))
        lines.append("")
    return "\n".join(lines)


def srt_bytes(subtitles: list[dict[str, Any]], offset_ms: int = 0) -> bytes:
    return render_srt(subtitles, offset_ms).encode("utf-8")
