"""视频工程导出阶段的媒体文件辅助函数。

该模块只处理临时文件、音频抽取和片头/片尾卡片生成，不参与项目状态机；
因此渲染编排服务可以专注于分段和导出生命周期。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import settings
from app.core.storage import storage
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.services.video_composer import render_title_card


def write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def extract_audio(video_path: Path, audio_path: Path) -> None:
    subprocess.run(
        [settings.ffmpeg_binary, '-y', '-i', str(video_path), '-vn', '-c:a', 'aac', '-ar', '48000', '-ac', '2', str(audio_path)],
        capture_output=True,
        timeout=120,
        check=False,
    )


def load_segment_item(seg: VideoSegment, tmp: Path) -> dict:
    data = storage.load(seg.output_key)
    video_path = tmp / f'seg_{seg.id}.mp4'
    write_bytes(video_path, data)
    audio_path = tmp / f'seg_{seg.id}.m4a'
    extract_audio(video_path, audio_path)
    return {
        'path': str(video_path),
        'audio_path': str(audio_path),
        'duration': seg.duration,
        'transition_type': seg.transition_type,
        'transition_duration': seg.transition_duration,
        'shot_id': seg.storyboard_shot_id,
    }


def build_open_card(vp: VideoProject, w: int, h: int, fps: int, tmp: Path) -> dict | None:
    cfg = vp.open_config or {}
    text = cfg.get('text') or vp.name or '工程投标视频'
    sub_text = cfg.get('sub_text') or ''
    if not text and not sub_text:
        return None
    duration = max(1.0, float(cfg.get('duration', 3.0)))
    data = render_title_card(text, sub_text, duration=duration, width=w, height=h, fps=fps, brand_color=cfg.get('brand_color') or vp.brand_color)
    video_path = tmp / 'open.mp4'
    write_bytes(video_path, data)
    audio_path = tmp / 'open.m4a'
    extract_audio(video_path, audio_path)
    return {'path': str(video_path), 'audio_path': str(audio_path), 'duration': duration, 'transition_type': 'fade', 'transition_duration': 0.5, 'shot_id': None}


def build_close_card(vp: VideoProject, w: int, h: int, fps: int, tmp: Path) -> dict | None:
    cfg = vp.close_config or {}
    text = cfg.get('text') or ''
    if not text:
        return None
    duration = max(1.0, float(cfg.get('duration', 3.0)))
    data = render_title_card(text, '投标人：企业承诺', duration=duration, width=w, height=h, fps=fps, brand_color=vp.brand_color)
    video_path = tmp / 'close.mp4'
    write_bytes(video_path, data)
    audio_path = tmp / 'close.m4a'
    extract_audio(video_path, audio_path)
    return {'path': str(video_path), 'audio_path': str(audio_path), 'duration': duration, 'transition_type': 'fade', 'transition_duration': 0.5, 'shot_id': None}
