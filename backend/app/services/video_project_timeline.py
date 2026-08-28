"""视频工程时间轴的可复用计算。

时间轴快照和项目级字幕不应和导出任务状态、存储上传混在一起；本模块保持
纯数据输入/输出，并通过回调读取分段字幕，便于单元测试和后续扩展多种导出格式。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.services.audio_utils import render_srt


def timeline_snapshot(vp: VideoProject, items: list[dict], segs: list[VideoSegment] | None = None) -> dict:
    return {
        'width': vp.width,
        'height': vp.height,
        'fps': vp.fps,
        'items': [
            {
                'shot_id': item.get('shot_id'),
                'duration': item['duration'],
                'transition_type': item['transition_type'],
                'transition_duration': item['transition_duration'],
            }
            for item in items
        ],
        'music_tracks': vp.music_tracks,
        'logo_config': vp.logo_config,
        'open_config': vp.open_config,
        'close_config': vp.close_config,
        'subtitle_style': vp.subtitle_style,
        'brand_color': vp.brand_color,
    }


def project_srt(
    db: Any,
    vp: VideoProject,
    items: list[dict],
    segs: list[VideoSegment],
    subtitle_resolver: Callable[[Any, VideoSegment], list[dict]],
) -> str:
    """按渲染顺序累计字幕时间，正确扣除相邻分段的转场重叠。"""
    all_subs: list[dict] = []
    offset = 0.0
    seg_by_shot = {segment.storyboard_shot_id: segment for segment in segs}
    for index, item in enumerate(items):
        shot_id = item.get('shot_id')
        segment = seg_by_shot.get(shot_id) if shot_id else None
        if segment:
            for subtitle in subtitle_resolver(db, segment):
                entry = dict(subtitle)
                entry['start_ms'] = int(round((offset + float(subtitle.get('start_ms', 0)) / 1000) * 1000))
                entry['end_ms'] = int(round((offset + float(subtitle.get('end_ms', 0)) / 1000) * 1000))
                all_subs.append(entry)
        transition = float(item.get('transition_duration', 0.0) or 0.0)
        offset += float(item['duration']) - (transition if index < len(items) - 1 else 0.0)
    return render_srt(all_subs)
