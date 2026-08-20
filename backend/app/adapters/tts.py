"""TTS 配音适配器：能力声明式（OpenAI 兼容 + Mock）。

能力声明 capabilities 供前端据此禁用不支持的参数。
未配置 API Key 时自动进入 Mock，Mock 生成真实的 WAV 文件
（PCM 16-bit / 48kHz / 单声道），用不同频率提示音模拟句子，
不声称是真实朗读，文件/界面标记 "Mock Audio"。
"""

from __future__ import annotations

import array
import hashlib
import math
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from app.adapters.base import BaseAIAdapter, MockMixin
from app.core.config import settings
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------- 能力枚举 ----------------
CAP_SYNTHESIZE = "synthesize"
CAP_SSML = "ssml"
CAP_TIMESTAMPS = "timestamps"
CAP_WORD_TIMESTAMPS = "word_timestamps"
CAP_SENTENCE_TIMESTAMPS = "sentence_timestamps"
CAP_SPEED_CONTROL = "speed_control"
CAP_PITCH_CONTROL = "pitch_control"
CAP_VOLUME_CONTROL = "volume_control"
CAP_EMOTION = "emotion"
CAP_STREAMING = "streaming"
CAP_VOICE_PREVIEW = "voice_preview"
CAP_MP3 = "mp3"
CAP_WAV = "wav"
CAP_VOICE_CLONING = "voice_cloning"

_ALL_TTS_CAPS = [
    CAP_SYNTHESIZE,
    CAP_SSML,
    CAP_TIMESTAMPS,
    CAP_WORD_TIMESTAMPS,
    CAP_SENTENCE_TIMESTAMPS,
    CAP_SPEED_CONTROL,
    CAP_PITCH_CONTROL,
    CAP_VOLUME_CONTROL,
    CAP_EMOTION,
    CAP_STREAMING,
    CAP_VOICE_PREVIEW,
    CAP_MP3,
    CAP_WAV,
    CAP_VOICE_CLONING,
]

# 通用音色（OpenAI 内置音色列表）
COMMON_VOICES = [
    {"id": "alloy", "name": "Alloy（均衡）", "gender": "neutral", "provider": "openai"},
    {"id": "echo", "name": "Echo（沉稳男声）", "gender": "male", "provider": "openai"},
    {"id": "fable", "name": "Fable（叙事）", "gender": "neutral", "provider": "openai"},
    {"id": "onyx", "name": "Onyx（深沉男声）", "gender": "male", "provider": "openai"},
    {"id": "nova", "name": "Nova（亲和女声）", "gender": "female", "provider": "openai"},
    {"id": "shimmer", "name": "Shimmer（清亮女声）", "gender": "female", "provider": "openai"},
]


class CapabilityError(AIProviderError):
    """Provider 不支持某能力（参数）。"""

    code = "CAPABILITY_NOT_SUPPORTED"


class TTSAdapter(BaseAIAdapter):
    """OpenAI 兼容 TTS 适配器。"""

    provider = "openai"

    CAPABILITIES = {
        CAP_SYNTHESIZE,
        CAP_SPEED_CONTROL,
        CAP_VOICE_PREVIEW,
        CAP_MP3,
        CAP_WAV,
    }

    def capabilities(self) -> dict[str, bool]:
        return {cap: cap in self.CAPABILITIES for cap in _ALL_TTS_CAPS}

    def supports(self, cap: str) -> bool:
        return cap in self.CAPABILITIES

    def is_available(self) -> bool:
        return bool(self.config.get("api_key"))

    def _client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self.config.get("api_key"),
            base_url=self.config.get("base_url") or None,
            timeout=self.config.get("timeout", 120),
        )

    def _require_capability(self, cap: str) -> None:
        if not self.supports(cap):
            raise CapabilityError(
                f"Provider {self.provider} 不支持 {cap}，请禁用对应前端参数。"
            )

    def list_voices(self) -> list[dict]:
        """返回可用音色列表。"""
        return list(COMMON_VOICES)

    def get_capabilities(self) -> dict[str, bool]:
        return self.capabilities()

    def preview_voice(
        self,
        *,
        voice: str | None = None,
        text: str | None = None,
        format: str = "mp3",
    ) -> bytes:
        """生成音色试听音频。"""
        self._require_capability(CAP_VOICE_PREVIEW)
        sample = text or "这是音色试听，用于在投标视频中使用。"
        return self.synthesize(sample, voice=voice, speed=1.0, format=format)

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        format: str = "mp3",
        pitch: float | None = None,
        volume: float | None = None,
        emotion: str | None = None,
        **kwargs: Any,
    ) -> bytes:
        """返回配音音频字节。"""
        if not self.is_available():
            self._raise_unavailable("tts")
        # Provider 不支持的参数必须明确报错，不得静默忽略
        if pitch is not None:
            self._require_capability(CAP_PITCH_CONTROL)
        if volume is not None:
            self._require_capability(CAP_VOLUME_CONTROL)
        if emotion is not None:
            self._require_capability(CAP_EMOTION)
        if format == "wav":
            self._require_capability(CAP_WAV)
        elif format == "mp3":
            self._require_capability(CAP_MP3)

        client = self._client()
        try:
            resp = client.audio.speech.create(
                model=self.config.get("model", "tts-1"),
                voice=voice or self.config.get("voice", "onyx"),
                input=text,
                speed=min(max(float(speed), 0.25), 4.0),
                response_format="wav" if format == "wav" else "mp3",
                **kwargs,
            )
            return resp.content
        except CapabilityError:
            raise
        except Exception as exc:
            logger.exception("tts_error")
            raise AIProviderError(self.normalize_error(exc)) from exc

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """真实 Provider 如需异步任务可在此实现；OpenAI 同步返回 None。"""
        return None

    def cancel_task(self, task_id: str) -> bool:
        """同步接口无需取消；异步 Provider 在此实现。"""
        return False

    def normalize_error(self, exc: Exception) -> str:
        """把 Provider 异常转成不含敏感信息的中文描述。"""
        msg = str(exc)
        if isinstance(exc, AIProviderError):
            return msg
        # 过滤可能含 Key 的内容，只保留简短信息
        if len(msg) > 300:
            msg = msg[:300] + "…"
        return f"TTS 调用失败: {msg}"


class MockTTSAdapter(TTSAdapter, MockMixin):
    """Mock TTS：生成真实的确定性 WAV（提示音模拟句子），标记 Mock Audio。"""

    provider = "mock"

    def is_available(self) -> bool:
        return True

    def capabilities(self) -> dict[str, bool]:
        caps = {
            CAP_SYNTHESIZE: True,
            CAP_SPEED_CONTROL: True,
            CAP_VOICE_PREVIEW: True,
            CAP_MP3: True,
            CAP_WAV: True,
        }
        return {cap: caps.get(cap, False) for cap in _ALL_TTS_CAPS}

    def supports(self, cap: str) -> bool:
        return self.capabilities().get(cap, False)

    def list_voices(self) -> list[dict]:
        return [
            {"id": "mock_male", "name": "Mock 男声（演示音）", "gender": "male", "provider": "mock"},
            {"id": "mock_female", "name": "Mock 女声（演示音）", "gender": "female", "provider": "mock"},
            {"id": "mock_tech", "name": "Mock 科技音（演示音）", "gender": "neutral", "provider": "mock"},
        ]

    def preview_voice(self, *, voice: str | None = None, text: str | None = None, format: str = "mp3") -> bytes:
        return self.synthesize(
            text or "音色试听，使用演示提示音。",
            voice=voice,
            speed=1.0,
            format=format,
            seed=42,
        )

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        format: str = "mp3",
        pitch: float | None = None,
        volume: float | None = None,
        emotion: str | None = None,
        seed: int | None = None,
        pause_strength: float = 1.0,
        **kwargs: Any,
    ) -> bytes:
        """Mock 合成：确定性 WAV，根据文字长度/标点/语速估算时长。"""
        # Mock 不支持 pitch/volume/emotion 时明确报错（除 None 外）
        if pitch is not None or volume is not None or emotion is not None:
            unsupported = [c for c in (pitch, volume, emotion) if c is not None]
            if unsupported:
                raise CapabilityError("Mock TTS 不支持音调/音量/情绪参数，请保持默认值。")

        time.sleep(0.3)  # 模拟耗时
        sample_rate = int(settings.tts_sample_rate or 48000)
        wav_bytes = generate_mock_wav(
            text,
            voice=voice,
            speed=speed,
            sample_rate=sample_rate,
            pause_strength=pause_strength,
            seed=seed,
        )
        if format == "mp3":
            return wav_to_mp3(wav_bytes)
        if format == "wav":
            return wav_bytes
        raise CapabilityError(f"Mock TTS 不支持输出格式: {format}")

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        return None

    def cancel_task(self, task_id: str) -> bool:
        return False

    def normalize_error(self, exc: Exception) -> str:
        return f"Mock TTS 错误: {exc}"


# ============================================================
# 火山引擎豆包语音合成（Volcengine Doubao Speech）
# ============================================================

# 火山引擎豆包语音合成 2.0 常用音色（resource_id 固定为 seed-tts-2.0）
VOLCENGINE_VOICES = [
    {"id": "zh_female_xiaohe_uranus_bigtts", "name": "小何 2.0（通用中文女声·默认）", "gender": "female", "provider": "volcengine"},
    {"id": "zh_female_vv_uranus_bigtts", "name": "Vivi 2.0（中/日，明亮女声）", "gender": "female", "provider": "volcengine"},
    {"id": "zh_female_cancan_uranus_bigtts", "name": "灿灿 2.0（温暖，适合通用叙事）", "gender": "female", "provider": "volcengine"},
    {"id": "zh_male_m191_uranus_bigtts", "name": "云舟 2.0（清晰男声，适合解说）", "gender": "male", "provider": "volcengine"},
    {"id": "zh_male_taocheng_uranus_bigtts", "name": "小天 2.0（稳重男声）", "gender": "male", "provider": "volcengine"},
    {"id": "zh_female_gaolengyujie_uranus_bigtts", "name": "高冷御姐 2.0（成熟冷静）", "gender": "female", "provider": "volcengine"},
    {"id": "zh_female_xinlingjitang_uranus_bigtts", "name": "心灵鸡汤 2.0（温暖治愈）", "gender": "female", "provider": "volcengine"},
    {"id": "zh_female_wenroushunv_uranus_bigtts", "name": "温柔淑女 2.0", "gender": "female", "provider": "volcengine"},
    {"id": "en_male_tim_uranus_bigtts", "name": "Tim（英文男声）", "gender": "male", "provider": "volcengine"},
    {"id": "en_female_dacey_uranus_bigtts", "name": "Dacey（英文女声）", "gender": "female", "provider": "volcengine"},
]


class VolcengineTTSAdapter(TTSAdapter):
    """火山引擎豆包语音合成适配器（火山语音技术产品线）。

    采用官方单向流式 SSE 接口：
    ``POST https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse``

    鉴权：新版控制台 API Key（``X-Api-Key``）+ ``X-Api-Resource-Id``（默认 seed-tts-2.0）。
    返回 mp3 / pcm / ogg_opus；**不直接返回 wav**，wav 由上游 any_audio_to_wav 转换。
    支持语速（speech_rate -50~100）、音调（pitch -12~12）、响度（loudness -50~100）。
    """

    provider = "volcengine"

    CAPABILITIES = {
        CAP_SYNTHESIZE,
        CAP_SPEED_CONTROL,
        CAP_PITCH_CONTROL,
        CAP_VOLUME_CONTROL,
        CAP_VOICE_PREVIEW,
        CAP_MP3,
        CAP_WAV,
    }

    def _endpoint(self) -> str:
        return str(
            self.config.get("base_url") or settings.volcengine_tts_base_url
        ).rstrip("/")

    def _resource_id(self) -> str:
        return str(
            self.config.get("resource_id") or settings.volcengine_tts_resource_id
        )

    def list_voices(self) -> list[dict]:
        return list(VOLCENGINE_VOICES)

    def _speech_rate(self, speed: float) -> int:
        """项目 speed 1.0 = 正常 → 豆包 speech_rate 0；0.5x→-50，2x→100。"""
        return max(-50, min(100, int(round((float(speed) - 1.0) * 100))))

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        format: str = "mp3",
        pitch: float | None = None,
        volume: float | None = None,
        emotion: str | None = None,
        **kwargs: Any,
    ) -> bytes:
        if not self.is_available():
            self._raise_unavailable("tts")
        if emotion is not None:
            raise CapabilityError("火山豆包 TTS 2.0 音色不支持 emotion 参数，请保持默认值。")

        # 音频格式：豆包原生返回 mp3/pcm/ogg_opus；wav 交给上游 any_audio_to_wav 转换
        output_format = "mp3"

        import base64
        import json
        import uuid

        import httpx

        speaker = str(voice or self.config.get("voice") or settings.volcengine_tts_voice)
        audio_params: dict[str, Any] = {
            "format": output_format,
            "speech_rate": self._speech_rate(speed),
            "loudness_rate": 0,
        }
        additions_dict: dict[str, Any] = {
            "disable_markdown_filter": True,
        }
        post_process: dict[str, Any] = {}
        if pitch is not None:
            # 豆包 pitch_rate 范围 -12~12（半音）；项目 pitch 1.0=正常
            post_process["pitch"] = max(-12, min(12, int(round((float(pitch) - 1.0) * 12))))
        if volume is not None:
            # 豆包 loudness_rate 范围 -50~100；项目 volume 1.0=正常
            post_process["loudness"] = max(-50, min(100, int(round((float(volume) - 1.0) * 100))))
        if post_process:
            additions_dict["post_process"] = post_process

        body = {
            "user": {"uid": "fastvideo"},
            "req_params": {
                "text": (text or "")[:5000],
                "speaker": speaker,
                "sample_rate": int(settings.tts_sample_rate or 48000),
                "audio_params": audio_params,
                "additions": json.dumps(additions_dict, ensure_ascii=False),
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self._resource_id(),
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Key": self.config.get("api_key"),
        }

        chunks: list[bytes] = []
        for line in self._stream_sse(headers, body):
            if not line or not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            code = d.get("code", 0)
            if code not in (0, 20000000):
                raise AIProviderError(
                    f"火山豆包语音合成失败（code={code}）: {d.get('message', '未知错误')}"
                )
            data = d.get("data")
            if data:
                chunks.append(base64.b64decode(data))

        if not chunks:
            raise AIProviderError("火山豆包语音合成未返回音频数据")
        audio = b"".join(chunks)
        if format == "wav":
            from app.services.audio_utils import any_audio_to_wav

            return any_audio_to_wav(audio, suffix=".mp3")
        if format == "mp3":
            return audio
        raise CapabilityError(f"火山豆包 TTS 不支持输出格式: {format}")

    def _stream_sse(self, headers: dict[str, Any], body: dict[str, Any]) -> list[str]:
        """发起 SSE 单向流式请求，返回逐行文本（形如 ``data: {...}``）。

        抽出为独立方法便于契约测试 mock；真实实现用 httpx 流式读取。
        """
        import httpx

        try:
            with httpx.Client(timeout=self.config.get("timeout", 120)) as client:
                with client.stream("POST", self._endpoint(), headers=headers, json=body) as resp:
                    resp.raise_for_status()
                    return list(resp.iter_lines())
        except AIProviderError:
            raise
        except Exception as exc:
            logger.exception("volcengine_tts_error")
            raise AIProviderError(self.normalize_error(exc)) from exc

    def preview_voice(self, *, voice: str | None = None, text: str | None = None, format: str = "mp3") -> bytes:
        sample = text or "这是音色试听，用于在投标视频中使用。"
        return self.synthesize(sample, voice=voice, speed=1.0, format=format)

    def normalize_error(self, exc: Exception) -> str:
        msg = str(exc)
        key = self.config.get("api_key")
        if key:
            msg = msg.replace(key, "[redacted]")
        if len(msg) > 300:
            msg = msg[:300] + "…"
        return f"火山豆包 TTS 调用失败: {msg}"


# ============================================================
# WAV 生成工具
# ============================================================

DEFAULT_SAMPLE_RATE = 48000


def _split_sentences(text: str) -> list[str]:
    """按中文/英文标点切分句子（保留标点），用于模拟不同句段。

    ASCII 句号 '.' 仅在其非数字夹持时切分，避免拆开小数点。
    """
    import re

    parts = re.split(r"(?<=[。！？；，、]|(?<![0-9])[.!?](?![0-9]))", text)
    return [p for p in parts if p.strip()]


def _stable_seed(text: str, voice: str | None, speed: float, seed: int | None) -> int:
    if seed is not None:
        return int(seed)
    raw = f"{text}|{voice}|{speed}"
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest()[:8], 16)


def generate_mock_wav(
    text: str,
    *,
    voice: str | None = None,
    speed: float = 1.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    pause_strength: float = 1.0,
    seed: int | None = None,
) -> bytes:
    """生成确定性 WAV：起始提示音 + 每个句段不同频率提示音 + 停顿。

    - PCM 16-bit / 单声道
    - 时长由文字长度、标点、语速与停顿强度决定
    - 相同 text/voice/speed/seed 结果可复现
    """
    voice = voice or "mock_male"
    seed_val = _stable_seed(text, voice, speed, seed)
    sentences = _split_sentences(text) or [text]

    # 语速基准：约 4.5 字/秒
    chars_per_second = 4.5 * max(0.5, min(float(speed), 2.0))

    def _char_len(s: str) -> float:
        # 中文字符按 1，连续字母/数字按 0.6 权重，标点忽略
        weight = 0.0
        for ch in s:
            if ch.isascii() and ch.isalnum():
                weight += 0.6
            elif ch.strip():
                weight += 1.0
        return weight

    # 频率随句段变化（并受 seed 影响，不同 seed 音色不同）
    base_freq = {"mock_male": 220, "mock_female": 330, "mock_tech": 440}.get(voice, 300)
    freq_step = 40
    seed_offset = seed_val % 60

    sample_count_total = 0
    buffer: list[int] = []

    def _add_tone(freq: float, seconds: float, volume: float = 0.35) -> None:
        nonlocal sample_count_total
        n = int(sample_rate * seconds)
        phase = 0.0
        fade = int(sample_rate * 0.02)  # 20ms 淡入淡出防爆音
        for i in range(n):
            env = 1.0
            if i < fade:
                env = i / fade
            elif i > n - fade:
                env = max(0.0, (n - i) / fade)
            # 轻微泛音，避免纯正弦过于刺耳
            value = (
                math.sin(2 * math.pi * freq * i / sample_rate + phase) * 0.8
                + math.sin(2 * math.pi * freq * 2 * i / sample_rate) * 0.15
            )
            sample = int(value * env * volume * 32767)
            buffer.append(sample)
            sample_count_total += 1

    def _add_silence(seconds: float) -> None:
        nonlocal sample_count_total
        n = int(sample_rate * seconds)
        buffer.extend([0] * n)
        sample_count_total += n

    # 起始提示音（明确标记为合成演示音）
    _add_tone(880, 0.12, volume=0.25)
    _add_silence(0.08)

    for idx, sentence in enumerate(sentences):
        freq = base_freq + (idx % 5) * freq_step + seed_offset
        chars = _char_len(sentence)
        seconds = max(0.35, chars / chars_per_second)
        _add_tone(freq, seconds)
        # 停顿：句号/感叹/问号更长；顿号/逗号更短
        tail = sentence[-1] if sentence else ""
        pause = 0.35 if tail in "。！？.!?" else (0.18 if tail in "，、,;" else 0.10)
        pause = pause * max(0.3, float(pause_strength))
        _add_silence(pause)

    # 末尾留一点静音
    _add_silence(0.15)

    return _pcm_to_wav(sample_rate, buffer)


def _pcm_to_wav(sample_rate: int, samples: list[int]) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        arr = array.array("h", samples)
        if _is_little_endian():
            arr.byteswap()  # array('h') 原生字节序，需转为小端
        wf.writeframes(arr.tobytes())
    return buf.getvalue()


def _is_little_endian() -> bool:
    import sys

    return sys.byteorder != "little"


def wav_to_mp3(wav_bytes: bytes, bitrate: str = "192k") -> bytes:
    """WAV → MP3（48kHz，默认 192kbps）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.wav"
        out = Path(tmp) / "output.mp3"
        src.write_bytes(wav_bytes)
        cmd = [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(src),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            "48000",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError as exc:
            logger.warning("wav_to_mp3_failed", stderr=exc.stderr.decode()[:500])
            raise AIProviderError(f"WAV 转 MP3 失败: {exc}")
        except FileNotFoundError:
            raise AIProviderError("未找到 ffmpeg，请安装 FFmpeg 后重试。")
        return out.read_bytes()


def generate_silent_audio(seconds: float, freq: int = 440) -> bytes:
    """兼容旧接口：用 FFmpeg 生成一段提示音 MP3。"""
    return wav_to_mp3(generate_mock_wav("演示音频", voice="mock_tech", seed=1))
