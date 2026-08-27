"""视频合成引擎（FFmpeg + 可选 RIFE）。

提供：
- 图片 → 动态分段（Ken Burns 运动 + 适配）
- 视频素材标准化（裁切/循环/冻结尾帧/变速）
- ASS 字幕生成与烧录
- 多分段转场拼接（xfade）
- 音频拼接（acrossfade）+ 背景音乐 + 自动 ducking
- Logo 叠加、片头片尾标题卡、音视频 mux
- Apple Silicon 上可用 rife-metal 做高质量补帧，选择 RIFE 时失败会明确报错

安全：所有 FFmpeg 调用使用参数数组 / 过滤器脚本文件，禁止把用户文本拼进 shell。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

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


@lru_cache(maxsize=1)
def _has_filter(name: str) -> bool:
    """检查当前 FFmpeg 是否带指定滤镜（发行版可能裁剪 drawtext）。"""
    try:
        proc = subprocess.run(
            [settings.ffmpeg_binary, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=20,
        )
        # `ffmpeg -filters` 的最后一列是说明文字，不能用最后一个 token 判断滤镜。
        # 过滤器名称位于中间列（例如 `ass V->V ...`、`drawtext V->V ...）。
        return proc.returncode == 0 and any(name in line.split() for line in proc.stdout.splitlines())
    except (OSError, subprocess.TimeoutExpired):
        return False


class _RifeUnavailable(RuntimeError):
    """RIFE 未安装或当前输入无法由 RIFE 处理。"""


def _rife_executable() -> str | None:
    configured = (settings.rife_binary or "").strip()
    if not configured:
        return None
    path = Path(configured)
    if path.is_file() and path.stat().st_mode & 0o111:
        return str(path)
    return shutil.which(configured)


def _rife_model_path(executable: str) -> str | None:
    configured = (settings.rife_model or "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    resolved = Path(executable).resolve()
    for parent in resolved.parents:
        if parent.name == "homebrew":
            candidate = parent / "share" / "rife-metal" / "rife-v4.26.rmw"
            if candidate.is_file():
                return str(candidate)
    candidate = resolved.parent.parent / "share" / "rife-metal" / "rife-v4.26.rmw"
    return str(candidate) if candidate.is_file() else None


def _run_rife_pair(executable: str, previous: Path, current: Path, output: Path) -> None:
    cmd = [executable, "-0", str(previous), "-1", str(current), "-o", str(output)]
    model = _rife_model_path(executable)
    if not model:
        raise _RifeUnavailable("未找到 rife-metal 模型文件，请配置 RIFE_MODEL")
    cmd.extend(["-m", model, "--tier", settings.rife_tier])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=max(30, int(settings.rife_timeout)),
        )
    except FileNotFoundError as exc:
        raise _RifeUnavailable("未找到 rife-metal") from exc
    except subprocess.TimeoutExpired as exc:
        raise _RifeUnavailable("rife-metal 处理超时") from exc
    if proc.returncode != 0 or not output.exists():
        detail = proc.stderr.decode(errors="replace")[-500:]
        raise _RifeUnavailable(f"rife-metal 执行失败：{detail}")


def _fit_video_filter(width: int, height: int, fit_mode: str) -> str:
    """返回不带输入/输出标签的画面适配滤镜，供 FFmpeg 与 RIFE 共用。"""
    if fit_mode == "fill":
        return f"scale={width}:{height}"
    if fit_mode == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if fit_mode == "blur":
        return (
            f"split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20[bgb];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


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


def _ass_filter_path(ass_path: str) -> str:
    """转义 ASS 文件路径，供 FFmpeg ass 滤镜使用。"""
    return str(ass_path).replace("\\", "\\\\").replace(":", "\\:")


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

        if ass_path and _has_filter("ass"):
            # ass 滤镜路径不使用 shell 引号；单引号在部分 FFmpeg 构建中会被当作路径字符。
            safe_ass = _ass_filter_path(ass_path)
            vf += f";[v]ass={safe_ass}[v]"

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

def _render_rife_segment(
    video_bytes: bytes,
    *,
    duration: float,
    fit_mode: str,
    width: int,
    height: int,
    fps: int,
    audio_bytes: bytes | None,
    volume: float,
    ass_path: str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> bytes:
    """使用 rife-metal 逐帧补中间帧，再由 FFmpeg 封装音视频。

    rife-metal 当前提供帧对帧 CLI，因此这里把视频拆成图片序列，逐对生成
    中间帧；输出序列按目标时长重新定时。RIFE 不可用或任一帧失败时直接报错，
    不静默切换到精度不同的 FFmpeg minterpolate。
    """
    executable = _rife_executable()
    if not executable:
        raise _RifeUnavailable("未安装 rife-metal，请配置 RIFE_BINARY")
    info = probe_media(video_bytes, suffix=".mp4")
    source_fps = float(info.get("fps") or fps or 24)
    if source_fps <= 0:
        source_fps = 24.0

    with _tmpdir() as tmp:
        src = _write(video_bytes, tmp / "src.mp4")
        source_frames = tmp / "source_frames"
        output_frames = tmp / "output_frames"
        source_frames.mkdir()
        output_frames.mkdir()

        # RIFE 处理的是画面帧；先统一画布，避免模型在每一对帧上重复缩放。
        fit = "cover" if fit_mode == "blur" else fit_mode
        vf = _fit_video_filter(width, height, fit)
        extract_cmd = [
            settings.ffmpeg_binary, "-y", "-i", str(src),
            "-vf", vf,
            "-vsync", "0", "-q:v", "2",
            str(source_frames / "frame_%08d.png"),
        ]
        try:
            _run(extract_cmd, timeout=max(120, int(settings.rife_timeout)))
        except RuntimeError as exc:
            raise _RifeUnavailable(f"RIFE 输入帧提取失败：{exc}") from exc

        frames = sorted(source_frames.glob("frame_*.png"))
        if len(frames) < 2:
            raise _RifeUnavailable("RIFE 至少需要两帧输入")

        # RIFE 是逐对帧推理，原先整个阶段一直停在 30%，容易被误认为卡死。
        # 将进度限制在 32~76%，把封装阶段留给上层的 80% 里程碑。
        if progress_callback:
            progress_callback(32, f"RIFE 已提取 {len(frames)} 帧，开始补帧…")

        output_index = 1
        shutil.copyfile(frames[0], output_frames / f"frame_{output_index:08d}.png")
        output_index += 1
        pair_count = len(frames) - 1
        last_progress = 32
        for pair_index, (previous, current) in enumerate(zip(frames, frames[1:]), start=1):
            middle = tmp / f"middle_{output_index:08d}.png"
            _run_rife_pair(executable, previous, current, middle)
            shutil.copyfile(middle, output_frames / f"frame_{output_index:08d}.png")
            output_index += 1
            shutil.copyfile(current, output_frames / f"frame_{output_index:08d}.png")
            output_index += 1
            if progress_callback:
                current_progress = 32 + int(42 * pair_index / max(pair_count, 1))
                if current_progress != last_progress:
                    last_progress = current_progress
                    progress_callback(current_progress, f"RIFE 补帧中… {pair_index}/{pair_count}")

        frame_count = output_index - 1
        # 让补帧后的整段恰好落在目标时长，再由 -r 统一到工程帧率。
        sequence_fps = max(1.0, frame_count / max(duration, 0.3))
        if audio_bytes:
            audio = _write(audio_bytes, tmp / "audio.wav")
        else:
            audio = _write(make_silence_wav(duration), tmp / "silence.wav")
        if progress_callback:
            progress_callback(76, "RIFE 补帧完成，正在封装视频…")
        out = tmp / "rife_segment.mp4"
        video_filter = "[0:v]"
        if ass_path and _has_filter("ass"):
            video_filter += f"ass={_ass_filter_path(ass_path)}[v]"
        else:
            video_filter += "null[v]"
        cmd = [
            settings.ffmpeg_binary, "-y",
            "-framerate", f"{sequence_fps:.6f}",
            "-i", str(output_frames / "frame_%08d.png"),
            "-i", str(audio),
            "-filter_complex", f"{video_filter};[1:a]{_audio_filter(duration, volume)}[a]",
            "-map", "[v]", "-map", "[a]", "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-movflags", "+faststart", str(out),
        ]
        try:
            _run(cmd, timeout=max(120, int(settings.rife_timeout)))
        except RuntimeError as exc:
            raise _RifeUnavailable(f"RIFE 输出封装失败：{exc}") from exc
        return _read(out)

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
    ass_path: str | None = None,
    short_video: str = "loop",  # loop | freeze | trim
    time_adaptation: str = "natural",  # natural | safe_stretch | rife | interpolate | loop | freeze | stretch
    progress_callback: Callable[[int, str], None] | None = None,
) -> bytes:
    """视频素材标准化，并按目标分段时长自动调整播放速度。"""
    duration = max(duration, 0.3)
    info = probe_media(video_bytes, suffix=".mp4")
    src_duration = float(info.get("duration_seconds") or 0)
    # 视频工程默认采用时间拉伸：不重复画面，按 source_duration / target_duration 调速。
    # 保留 loop/trim 模式供底层兼容调用。
    speed_ratio = (src_duration / duration) if src_duration > 0 else 1.0
    if time_adaptation == "rife":
        try:
            return _render_rife_segment(
                video_bytes,
                duration=duration,
                fit_mode=fit_mode,
                width=width,
                height=height,
                fps=fps,
                audio_bytes=audio_bytes,
                volume=volume,
                ass_path=ass_path,
                progress_callback=progress_callback,
            )
        except _RifeUnavailable as exc:
            # RIFE 是用户明确选择的高质量策略，不允许静默降级导致结果质量变化。
            logger.error("rife_required_but_unavailable", reason=str(exc))
            if progress_callback:
                progress_callback(35, f"RIFE 失败：{str(exc)[:100]}")
            raise
    # 旧 stretch 调用保留兼容，但只有安全区间才允许改变速度，避免 10/15 秒视频被强行慢放。
    stretch = time_adaptation in ("stretch", "safe_stretch") and src_duration > 0 and 0.85 <= speed_ratio <= 1.15
    loop = time_adaptation == "loop" or (time_adaptation == "natural" and short_video == "loop" and src_duration < duration)

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
        if stretch:
            time_scale = duration / src_duration
            vf += f",setpts={time_scale:.6f}*PTS"
        elif time_adaptation == "freeze" and src_duration > 0 and src_duration < duration:
            vf += f",tpad=stop_mode=clone:stop_duration={max(duration-src_duration, 0):.3f}"
        elif time_adaptation == "interpolate" and src_duration > 0 and speed_ratio < 1:
            # 先把时间轴放慢到目标时长，再用运动插值补足中间帧；否则仅提高 fps
            # 只会复制帧，无法解决 10/15 秒成片的卡顿问题。
            time_scale = duration / src_duration
            vf += f",setpts={time_scale:.6f}*PTS,minterpolate=mi_mode=mci:mc_mode=aobmc:me_mode=bidir"
        vf += f",fps={fps},format=yuv420p[v]"
        if ass_path and _has_filter("ass"):
            vf += f";[v]ass={_ass_filter_path(ass_path)}[v]"

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
            # 分段预览/中间产物优先响应速度，正式导出仍由最终合成阶段统一编码。
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
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
    ass_path: str | None = None,
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
        if _has_filter("drawtext"):
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
        else:
            # 没有 drawtext 时仍输出可播放的纯色标题卡，不能让整条导出链失败。
            draw = "format=yuv420p"
        # 淡入淡出
        vf = f"[0:v]{draw},fade=t=in:d=0.4,fade=t=out:st={max(0, duration - 0.5)}:d=0.5,fps={fps},format=yuv420p[v]"
        if ass_path and _has_filter("ass"):
            vf += f";[v]ass={_ass_filter_path(ass_path)}[v]"

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
