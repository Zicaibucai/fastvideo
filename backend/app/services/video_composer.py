"""视频合成引擎（FFmpeg）。

提供：
- 图片 → 动态分段（Ken Burns 运动 + 适配）
- 视频素材标准化（裁切/循环/冻结尾帧/变速）
- ASS 字幕生成与烧录
- 多分段转场拼接（xfade）
- 音频拼接（acrossfade）+ 背景音乐 + 自动 ducking
- Logo 叠加、片头片尾标题卡、音视频 mux

安全：所有 FFmpeg 调用使用参数数组 / 过滤器脚本文件，禁止把用户文本拼进 shell。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

AUDIO_SAMPLE_RATE = 48000
DEFAULT_FONT = "Noto Serif CJK SC"

# transition_type -> xfade transition 名称
XFADE_MAP = {
    "none": "fade",
    "fade": "fade",
    "crossfade": "dissolve",
    "black": "fadeblack",
    "white": "fadewhite",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "tech_mask": "dissolve",
}
# "none" 转场也用极小交叉淡入淡出保证 xfade 有效（近似硬切）
NONE_TRANSITION_DURATION = 0.1

MOTIONS = {
    "static": ("1", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2", 1.0),
    "zoom_in": ("min(1+0.0015*on,1.15)", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2", 1.0),
    "zoom_out": ("max(1.15-0.0015*on,1.0)", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2", 1.15),
    "pan_left": ("1.15", "(iw-iw/zoom)*(1-on/({frames}-1))", "(ih-ih/zoom)/2", 1.15),
    "pan_right": ("1.15", "(iw-iw/zoom)*on/({frames}-1)", "(ih-ih/zoom)/2", 1.15),
    "pan_up": ("1.15", "(iw-iw/zoom)/2", "(ih-ih/zoom)*(1-on/({frames}-1))", 1.15),
    "pan_down": ("1.15", "(iw-iw/zoom)/2", "(ih-ih/zoom)*on/({frames}-1)", 1.15),
}


# ============================================================
# 基础工具
# ============================================================

@contextmanager
def _tmpdir():
    d = tempfile.TemporaryDirectory(prefix="fv_video_")
    try:
        yield Path(d.name)
    finally:
        d.cleanup()


def _write(data: bytes, path: Path) -> Path:
    path.write_bytes(data)
    return path


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _run(cmd: list[str], timeout: int = 600) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("未找到 ffmpeg，请安装 FFmpeg。")
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace")
        logger.warning("ffmpeg_failed", cmd=" ".join(str(c) for c in cmd[:8]), stderr=stderr[-600:])
        raise RuntimeError(f"FFmpeg 处理失败: {stderr[-900:]}")


def probe_media(data: bytes, suffix: str = ".mp4") -> dict[str, Any]:
    """用 ffprobe 读取媒体信息。"""
    with _tmpdir() as tmp:
        src = tmp / f"in{suffix}"
        _write(data, src)
        cmd = [
            settings.ffprobe_binary, "-v", "error",
            "-show_entries",
            "format=duration:stream=codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels",
            "-of", "json", str(src),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise RuntimeError("未找到 ffprobe，请安装 FFmpeg。")
        if proc.returncode != 0:
            return {"decodable": False, "error": proc.stderr[:300]}
        info = json.loads(proc.stdout or "{}")
        fmt = info.get("format", {})
        streams = info.get("streams", [])
        vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
        astream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        def _fps(s):
            r = (s or {}).get("r_frame_rate")
            if r and "/" in r:
                try:
                    num, den = r.split("/")
                    return round(float(num) / max(1, float(den)), 3)
                except (ValueError, ZeroDivisionError):
                    return None
            return None

        try:
            duration = float(fmt.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        return {
            "decodable": True,
            "duration_seconds": round(duration, 3),
            "width": (vstream or {}).get("width"),
            "height": (vstream or {}).get("height"),
            "fps": _fps(vstream),
            "vcodec": (vstream or {}).get("codec_name"),
            "acodec": (astream or {}).get("codec_name"),
            "has_audio": astream is not None,
            "sample_rate": (astream or {}).get("sample_rate"),
            "channels": (astream or {}).get("channels"),
        }


def make_silence_wav(duration: float) -> bytes:
    """生成指定时长的静音 WAV（16-bit/48kHz/立体声）。"""
    import array
    import io
    import wave

    buf = io.BytesIO()
    n = int(duration * AUDIO_SAMPLE_RATE) * 2  # 双声道
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_SAMPLE_RATE)
        wf.writeframes(array.array("h", [0] * n).tobytes())
    return buf.getvalue()


# ============================================================
# 过滤器脚本
# ============================================================

def _audio_filter(duration: float, volume: float = 1.0) -> str:
    return (
        f"volume={volume},aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
        f"apad=whole_dur={max(duration, 0.1)},atrim=duration={max(duration, 0.1)}"
    )


def _motion_expr(motion: str, frames: int) -> tuple[str, str, str]:
    z, x, y, _start = MOTIONS.get(motion, MOTIONS["zoom_in"])
    x = x.replace("{frames}", str(max(frames, 2)))
    y = y.replace("{frames}", str(max(frames, 2)))
    return z, x, y


# ============================================================
# 图片 → 分段
# ============================================================

def render_image_segment(
    image_bytes: bytes,
    *,
    duration: float,
    motion: str = "zoom_in",
    fit_mode: str = "cover",
    width: int = 1920,
    height: int = 1080,
    fps: int = 25,
    audio_bytes: bytes | None = None,
    volume: float = 1.0,
    bg_color: str = "#1E3A5F",
    ass_path: str | None = None,
) -> bytes:
    """把静态图片渲染为标准化动态分段（H.264/AAC，含音频轨）。"""
    duration = max(duration, 0.3)
    frames = int(round(duration * fps))
    with _tmpdir() as tmp:
        img = tmp / "img.png"
        _write(image_bytes, img)
        inputs: list[str] = ["-y", "-i", str(img)]

        # 音频
        audio_path: Path | None = None
        if audio_bytes:
            audio_path = tmp / "audio.wav"
            _write(audio_bytes, audio_path)
            inputs += ["-i", str(audio_path)]

        # 视频过滤器（适配 + 运动）
        if fit_mode in ("contain", "blur"):
            # 保持比例、不拉伸；contain 黑边 / blur 模糊背景填充
            if fit_mode == "contain":
                vf = (
                    f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"fps={fps},format=yuv420p[v]"
                )
            else:
                vf = (
                    f"[0:v]split=2[bg][fg];"
                    f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},boxblur=20[bgb];"
                    f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fgs];"
                    f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,"
                    f"fps={fps},format=yuv420p[v]"
                )
        else:
            # cover / fill：缩放填满 + Ken Burns
            if fit_mode == "fill":
                pre = f"[0:v]scale={width}:{height}"
            else:
                pre = (
                    f"[0:v]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height}"
                )
            z, x, y = _motion_expr(motion, frames)
            vf = (
                f"{pre},zoompan=z='{z}':d={frames}:x='{x}':y='{y}':"
                f"s={width}x{height}:fps={fps},format=yuv420p[v]"
            )

        if ass_path:
            vf += f";[v]ass='{ass_path}'[v]"

        if audio_path:
            graph = f"{vf};[1:a]{_audio_filter(duration, volume)}[a]"
        else:
            # 静音轨
            silence = tmp / "silence.wav"
            _write(make_silence_wav(duration), silence)
            inputs += ["-i", str(silence)]
            graph = f"{vf};[1:a]{_audio_filter(duration, volume)}[a]"

        out = tmp / "seg.mp4"
        cmd = [
            settings.ffmpeg_binary,
            *inputs,
            "-filter_complex", graph,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-movflags", "+faststart",
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# 视频素材 → 分段
# ============================================================

def render_video_segment(
    video_bytes: bytes,
    *,
    duration: float,
    fit_mode: str = "cover",
    motion: str = "static",
    width: int = 1920,
    height: int = 1080,
    fps: int = 25,
    audio_bytes: bytes | None = None,
    volume: float = 1.0,
    short_video: str = "loop",  # loop | freeze | trim
) -> bytes:
    """视频素材标准化：统一 H.264/AAC/分辨率/fps，短素材可循环或冻结尾帧。"""
    duration = max(duration, 0.3)
    info = probe_media(video_bytes, suffix=".mp4")
    src_duration = float(info.get("duration_seconds") or 0)
    loop = short_video == "loop" and src_duration < duration

    with _tmpdir() as tmp:
        src = tmp / "src.mp4"
        _write(video_bytes, src)
        inputs: list[str] = ["-y"]
        if loop:
            inputs += ["-stream_loop", "-1"]
        inputs += ["-i", str(src)]

        # 适配（不拉伸建筑主体）
        if fit_mode == "fill":
            vf = f"[0:v]scale={width}:{height}"
        elif fit_mode == "contain":
            vf = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        elif fit_mode == "blur":
            vf = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},boxblur=20[bgb];"
                f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
            )
        else:  # cover
            vf = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )
        vf += f",fps={fps},format=yuv420p[v]"

        audio_path: Path | None = None
        if audio_bytes:
            audio_path = tmp / "audio.wav"
            _write(audio_bytes, audio_path)
            inputs += ["-i", str(audio_path)]
        else:
            silence = tmp / "silence.wav"
            _write(make_silence_wav(duration), silence)
            inputs += ["-i", str(silence)]
        graph = f"{vf};[1:a]{_audio_filter(duration, volume)}[a]"

        out = tmp / "seg.mp4"
        cmd = [
            settings.ffmpeg_binary,
            *inputs,
            "-filter_complex", graph,
            "-map", "[v]", "-map", "[a]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-movflags", "+faststart",
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# 标题卡（片头 / 片尾 / 章节卡）
# ============================================================

def render_title_card(
    text: str,
    sub_text: str | None,
    *,
    duration: float,
    width: int = 1920,
    height: int = 1080,
    fps: int = 25,
    brand_color: str = "#1E3A5F",
    audio_bytes: bytes | None = None,
) -> bytes:
    """生成标题卡视频（品牌色背景 + 居中文字 + 静音/音频轨）。"""
    duration = max(duration, 1.0)
    with _tmpdir() as tmp:
        color = brand_color.lstrip("#") or "1E3A5F"
        txt = tmp / "text.txt"
        safe_text = text.replace("\n", " ")
        _write(safe_text.encode("utf-8"), txt)

        inputs = [
            "-y", "-f", "lavfi",
            "-i", f"color=c=0x{color}:s={width}x{height}:d={duration}:r={fps}",
        ]
        # drawtext 使用 textfile 避免命令注入
        draw = (
            f"drawtext=textfile='{txt}':fontcolor=white:fontsize={int(height * 0.08)}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-60"
        )
        if sub_text:
            sub = tmp / "sub.txt"
            _write(sub_text.replace("\n", " ").encode("utf-8"), sub)
            draw += (
                f",drawtext=textfile='{sub}':fontcolor=white@0.85:fontsize={int(height * 0.04)}:"
                f"x=(w-text_w)/2:y=(h-text_h)/2+60"
            )
        # 淡入淡出
        vf = f"[0:v]{draw},fade=t=in:d=0.4,fade=t=out:st={max(0, duration - 0.5)}:d=0.5,fps={fps},format=yuv420p[v]"

        if audio_bytes:
            audio_path = tmp / "audio.wav"
            _write(audio_bytes, audio_path)
            inputs += ["-i", str(audio_path)]
            graph = f"{vf};[1:a]{_audio_filter(duration, 1.0)}[a]"
        else:
            silence = tmp / "silence.wav"
            _write(make_silence_wav(duration), silence)
            inputs += ["-i", str(silence)]
            graph = f"{vf};[1:a]{_audio_filter(duration, 1.0)}[a]"

        out = tmp / "card.mp4"
        cmd = [
            settings.ffmpeg_binary,
            *inputs,
            "-filter_complex", graph,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# ASS 字幕
# ============================================================

def _ass_time(ms: float) -> str:
    cs = int(round(ms / 10))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _ass_color(color: str) -> str:
    """'white'/'black'/'red' 或 hex 转 ASS &HAABBGGRR。"""
    hexmap = {"white": "FFFFFF", "black": "000000", "yellow": "FFFF00", "red": "FF0000"}
    hexval = hexmap.get(color.lower(), color.lstrip("#")) if isinstance(color, str) else "FFFFFF"
    hexval = (hexval or "FFFFFF").ljust(6, "0")[:6]
    bb = hexval[2:4]
    gg = hexval[0:2]
    rr = hexval[4:6]
    return f"&H00{bb}{gg}{rr}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def build_ass(
    subtitles: list[dict[str, Any]],
    *,
    style: dict[str, Any] | None = None,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """生成 ASS 字幕文件内容。"""
    style = style or {}
    font_size = int(style.get("font_size", 46))
    font_color = _ass_color(style.get("font_color", "white"))
    stroke_color = _ass_color(style.get("stroke_color", "black"))
    shadow_color = _ass_color("black")
    stroke = float(style.get("stroke_width", 1.2))
    shadow = 1.0 if style.get("shadow", True) else 0.0
    alignment = 8 if style.get("position") == "top" else 2
    margin_v = 90 if alignment == 2 else 60
    bg_alpha = max(0.0, min(1.0, float(style.get("bg_opacity", 0.0))))
    bg_col = int(round(bg_alpha * 255))

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{DEFAULT_FONT},{font_size},&H{font_color[2:]},&H{font_color[2:]},"
        f"&H{stroke_color[2:]},&H{bg_col:02X}000000,0,0,0,0,100,100,0,0,"
        f"1,{stroke},{shadow},{alignment},60,60,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for sub in subtitles:
        start = _ass_time(float(sub.get("start_ms", 0)))
        end = _ass_time(float(sub.get("end_ms", 0)))
        text = _ass_escape(str(sub.get("text", ""))).strip()
        if not text:
            continue
        # 最多两行（保持原换行）
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return header + "\n".join(lines)


# ============================================================
# 转场拼接
# ============================================================

def _effective_transition(trans_type: str, trans_duration: float) -> tuple[str, float]:
    if trans_type in ("", None, "none"):
        return "fade", NONE_TRANSITION_DURATION
    return XFADE_MAP.get(trans_type, "dissolve"), max(trans_duration, NONE_TRANSITION_DURATION)


def concat_with_transitions(
    items: list[dict[str, Any]],
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 25,
) -> tuple[bytes, float]:
    """用 xfade 拼接多个分段视频。

    items: [{path, duration, transition_type, transition_duration}]
    返回 (mp4 bytes, 总时长)。总时长 = 各段时长之和 - 转场时长之和。
    """
    if not items:
        raise RuntimeError("没有可拼接的分段")
    n = len(items)
    with _tmpdir() as tmp:
        inputs: list[str] = ["-y"]
        paths: list[Path] = []
        for i, it in enumerate(items):
            p = tmp / f"seg{i}.mp4"
            _write(Path(it["path"]).read_bytes(), p)
            paths.append(p)
            inputs += ["-i", str(p)]

        graph_parts: list[str] = []
        prev_label = "0:v"
        durations = [float(it["duration"]) for it in items]
        transitions: list[tuple[str, float]] = []
        for it in items:
            transitions.append(_effective_transition(it.get("transition_type"), float(it.get("transition_duration", 0.5))))
        # offset_k = sum(durations[0..k]) - sum(transitions[0..k])
        cum_dur = 0.0
        cum_trans = 0.0
        for i in range(n - 1):
            trans, dur = transitions[i]
            label = f"v{i + 1}"
            offset = (cum_dur + durations[i]) - (cum_trans + dur)
            graph_parts.append(
                f"[{prev_label}][{i + 1}:v]xfade=transition={trans}:duration={dur}:offset={offset:.3f}[{label}]"
            )
            cum_dur += durations[i]
            cum_trans += dur
            prev_label = label
        total = sum(durations) - sum(transitions[i][1] for i in range(n - 1))
        graph_parts.append(f"[v{n - 1}]format=yuv420p,settb=AVTB[vout]")

        script = tmp / "graph.txt"
        script.write_text(";\n".join(graph_parts) + "\n", encoding="utf-8")

        out = tmp / "out.mp4"
        cmd = [
            settings.ffmpeg_binary,
            *inputs,
            "-filter_complex_script", str(script),
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-movflags", "+faststart",
            str(out),
        ]
        _run(cmd)
        return _read(out), round(total, 3)


def concat_audio(items: list[dict[str, Any]], total_duration: float) -> bytes:
    """用 acrossfade 拼接分段音频（转场时长一致）。"""
    n = len(items)
    if n == 0:
        return make_silence_wav(total_duration)
    if n == 1:
        return Path(items[0]["path"]).read_bytes()
    with _tmpdir() as tmp:
        inputs: list[str] = ["-y"]
        for i, it in enumerate(items):
            p = tmp / f"a{i}.m4a"
            _write(Path(it["path"]).read_bytes(), p)
            inputs += ["-i", str(p)]
        graph_parts: list[str] = []
        prev = "0:a"
        for i in range(n - 1):
            _, dur = _effective_transition(items[i].get("transition_type"), float(items[i].get("transition_duration", 0.5)))
            label = f"a{i + 1}"
            graph_parts.append(f"[{prev}][{i + 1}:a]acrossfade=d={dur}:c1=tri:c2=tri[{label}]")
            prev = label
        graph_parts.append(f"[a{n - 1}]aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo[aout]")
        script = tmp / "agraph.txt"
        script.write_text(";\n".join(graph_parts) + "\n", encoding="utf-8")
        out = tmp / "aout.m4a"
        cmd = [
            settings.ffmpeg_binary,
            *inputs,
            "-filter_complex_script", str(script),
            "-map", "[aout]",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-t", str(max(total_duration, 0.3)),
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# 背景音乐
# ============================================================

def build_music_track(
    tracks: list[dict[str, Any]],
    *,
    total_duration: float,
) -> bytes:
    """把一首或多首背景音乐铺满整片（循环 + 淡入淡出 + 音量）。

    tracks: [{path, volume, fade_in, fade_out}]
    """
    if not tracks:
        return make_silence_wav(total_duration)
    total_duration = max(total_duration, 0.5)
    with _tmpdir() as tmp:
        clips: list[Path] = []
        n = len(tracks)
        part = total_duration / n
        for i, tr in enumerate(tracks):
            src = tr["path"]
            volume = float(tr.get("volume", 0.7))
            fade_in = float(tr.get("fade_in", 1.0))
            fade_out = float(tr.get("fade_out", 2.0))
            # 该段时长
            seg_dur = part if i < n - 1 else total_duration - part * (n - 1)
            fade_in = min(fade_in, seg_dur / 2)
            fade_out = min(fade_out, seg_dur / 2)
            fade_out_start = max(0.0, seg_dur - fade_out)
            out_clip = tmp / f"music{i}.m4a"
            cmd = [
                settings.ffmpeg_binary,
                "-y", "-stream_loop", "-1", "-i", str(src),
                "-af",
                f"volume={volume},afade=t=in:d={fade_in},afade=t=out:st={fade_out_start}:d={fade_out},"
                f"aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo",
                "-t", str(max(seg_dur, 0.1)),
                "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
                str(out_clip),
            ]
            _run(cmd)
            clips.append(out_clip)

        # 拼接各音乐片段
        if len(clips) == 1:
            return _read(clips[0])
        list_file = tmp / "music_list.txt"
        with list_file.open("w", encoding="utf-8") as f:
            for c in clips:
                f.write(f"file '{c.resolve()}'\n")
        out = tmp / "music_all.m4a"
        cmd = [
            settings.ffmpeg_binary, "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-t", str(total_duration),
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# 混音（配音优先 + ducking）
# ============================================================

def duck_and_mix(dub_bytes: bytes, music_bytes: bytes | None, *, ducking: bool = True) -> bytes:
    """配音 + 背景音乐混音：配音出现时自动压低音乐，防削波。"""
    with _tmpdir() as tmp:
        dub = tmp / "dub.m4a"
        _write(dub_bytes, dub)
        inputs = ["-y", "-i", str(dub)]
        if music_bytes:
            music = tmp / "music.m4a"
            _write(music_bytes, music)
            inputs += ["-i", str(music)]

        if music_bytes and ducking:
            graph = (
                "[0:a]volume=1.0[dub];"
                # sidechaincompress: 主输入为音乐，sidechain 直接用配音输入流
                "[1:a][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=50:release=400[ducked];"
                "[dub][ducked]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.95[aout]"
            )
        elif music_bytes:
            graph = (
                "[0:a]volume=1.0[dub];[1:a]volume=0.7[mus];"
                "[dub][mus]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.95[aout]"
            )
        else:
            graph = "[0:a]alimiter=limit=0.95[aout]"

        script = tmp / "mix.txt"
        script.write_text(graph, encoding="utf-8")
        out = tmp / "mix.m4a"
        cmd = [
            settings.ffmpeg_binary,
            *inputs,
            "-filter_complex_script", str(script),
            "-map", "[aout]",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# Logo 叠加 / 音视频 mux
# ============================================================

def overlay_logo(
    video_bytes: bytes,
    logo_bytes: bytes,
    *,
    position: str = "top_right",
    size_ratio: float = 0.12,
    opacity: float = 0.9,
) -> bytes:
    with _tmpdir() as tmp:
        vid = tmp / "video.mp4"
        logo = tmp / "logo.png"
        _write(video_bytes, vid)
        _write(logo_bytes, logo)

        # 读取视频宽高
        info = probe_media(video_bytes, suffix=".mp4")
        w = info.get("width") or 1920
        h = info.get("height") or 1080
        logo_w = int(w * size_ratio)
        margin = int(w * 0.02)

        pos_map = {
            "top_left": (margin, margin),
            "top_right": (w - logo_w - margin, margin),
            "bottom_left": (margin, h - margin),
            "bottom_right": (w - logo_w - margin, h - margin),
        }
        x, y = pos_map.get(position, (w - logo_w - margin, margin))

        graph = (
            f"[1:v]scale={logo_w}:-1,format=rgba,colorchannelmixer=aa={opacity}[lg];"
            f"[0:v][lg]overlay={x}:{y}:format=auto[vout]"
        )
        script = tmp / "logo.txt"
        script.write_text(graph, encoding="utf-8")
        out = tmp / "out.mp4"
        cmd = [
            settings.ffmpeg_binary, "-y",
            "-i", str(vid), "-i", str(logo),
            "-filter_complex_script", str(script),
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(out),
        ]
        _run(cmd)
        return _read(out)


def mux(video_bytes: bytes, audio_bytes: bytes, *, fps: int = 25) -> bytes:
    """把视频轨与音频轨合成为最终 MP4。"""
    with _tmpdir() as tmp:
        vid = tmp / "video.mp4"
        aud = tmp / "audio.m4a"
        _write(video_bytes, vid)
        _write(audio_bytes, aud)
        out = tmp / "final.mp4"
        cmd = [
            settings.ffmpeg_binary, "-y",
            "-i", str(vid), "-i", str(aud),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ]
        _run(cmd)
        return _read(out)


# ============================================================
# 输入哈希（缓存）
# ============================================================

def compute_input_hash(**kwargs: Any) -> str:
    """对影响渲染结果的输入做确定性哈希，用于分段缓存复用。"""
    payload = json.dumps(kwargs, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
