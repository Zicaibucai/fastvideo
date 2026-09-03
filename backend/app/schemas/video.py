"""视频工程与导出 Schema（Phase 5）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedModel


# ============================================================
# 视频工程
# ============================================================

class TimelineItemIn(BaseModel):
    shot_id: str
    sequence: int
    duration: float | None = None
    fit_mode: str | None = None
    transition_type: str | None = None
    transition_duration: float | None = None
    subtitle_enabled: bool | None = None
    volume: float | None = None
    is_locked: bool | None = None
    visual_asset_id: str | None = None
    audio_version_id: str | None = None


class MusicTrackIn(BaseModel):
    asset_id: str
    name: str | None = None
    volume: float = 0.7
    fade_in: float = 1.0
    fade_out: float = 2.0
    loop: bool = True
    authorization_status: str = "approved"
    authorization_note: str | None = None


class LogoConfig(BaseModel):
    asset_id: str
    position: str = "top_right"  # top_left | top_right | bottom_left | bottom_right
    size: float = 0.12  # 相对画布宽度比例
    opacity: float = 0.9


class OpenConfig(BaseModel):
    text: str = ""
    sub_text: str | None = None
    music_asset_id: str | None = None
    duration: float = 3.0
    brand_color: str | None = None


class CloseConfig(BaseModel):
    text: str = ""
    duration: float = 3.0


class SubtitleStyle(BaseModel):
    font_size: int = 46
    font_color: str = "white"
    stroke_width: float = 1.2
    stroke_color: str = "black"
    shadow: bool = True
    position: str = "bottom"  # bottom | top
    bg_opacity: float = 0.3
    max_lines: int = 2


class VideoProjectCreate(BaseModel):
    project_id: str | None = None
    name: str
    width: int = 1920
    height: int = 1080
    fps: int = 24
    watermark_text: str | None = None
    brand_color: str = "#1E3A5F"
    export_mode: str = "demo"
    subtitle_style: SubtitleStyle | None = None
    music_tracks: list[MusicTrackIn] | None = None
    logo_config: LogoConfig | None = None
    open_config: OpenConfig | None = None
    close_config: CloseConfig | None = None
    timeline: list[TimelineItemIn] | None = None


class VideoProjectUpdate(BaseModel):
    name: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = Field(default=None, ge=24, le=30)
    watermark_text: str | None = None
    brand_color: str | None = None
    export_mode: str | None = None
    subtitle_style: SubtitleStyle | None = None
    music_tracks: list[MusicTrackIn] | None = None
    logo_config: LogoConfig | None = None
    open_config: OpenConfig | None = None
    close_config: CloseConfig | None = None
    timeline: list[TimelineItemIn] | None = None
    base_revision: int | None = Field(default=None, description="乐观锁版本，不一致返回 409")


class VideoProjectOut(TimestampedModel):
    project_id: str | None
    name: str
    status: str
    width: int
    height: int
    fps: int
    duration_seconds: float | None
    timeline: list | None
    subtitle_style: dict | None
    music_tracks: list | None
    logo_config: dict | None
    open_config: dict | None
    close_config: dict | None
    brand_color: str
    export_mode: str
    timeline_snapshot: dict | None
    output_key: str | None
    output_url: str | None
    watermark_text: str | None


# ============================================================
# 视频分段
# ============================================================
    revision: int = 1

class VideoSegmentOut(TimestampedModel):
    video_project_id: str
    storyboard_shot_id: str | None
    sequence: int
    visual_asset_id: str | None
    audio_version_id: str | None
    duration: float
    time_adaptation: str | None
    is_locked: bool
    fit_mode: str
    transition_type: str
    transition_duration: float
    subtitle_enabled: bool
    volume: float
    render_status: str
    render_progress: int
    output_key: str | None
    output_url: str | None
    input_hash: str | None
    needs_rebuild: bool
    error_message: str | None
    rendered_at: str | None
    # 解析后的信息
    shot_title: str | None = None
    narration: str | None = None
    visual_url: str | None = None
    visual_source_duration: float | None = None
    visual_playback_speed: float | None = None
    audio_url: str | None = None
    has_visual: bool = False
    has_audio: bool = False
    has_subtitle: bool = False
    visual_source: str | None = None  # manual | video | image | model_shot | placeholder | none
    revision: int = 1

class VideoSegmentPatch(BaseModel):
    duration: float | None = None
    time_adaptation: str | None = None
    is_locked: bool | None = None
    fit_mode: str | None = None
    transition_type: str | None = None
    transition_duration: float | None = None
    subtitle_enabled: bool | None = None
    volume: float | None = None
    visual_asset_id: str | None = None
    audio_version_id: str | None = None
    sequence: int | None = None
    base_revision: int | None = Field(default=None, description="乐观锁版本，不一致返回 409")



class SegmentsReorderIn(BaseModel):
    segment_ids: list[str]


# ============================================================
# 同步 / 预检 / 导出
# ============================================================

class SyncStoryboardOut(BaseModel):
    synced: bool
    created: int
    updated: int
    segment_count: int
    segments: list[VideoSegmentOut]


class PreflightIssue(BaseModel):
    level: str  # error | warning
    code: str
    message: str


class PreflightOut(BaseModel):
    ok: bool
    mode: str
    issues: list[PreflightIssue]
    segment_count: int
    rendered_segment_count: int
    missing_render_count: int
    review_policy: str = "recommended"
    mock_mode: bool = False


class ExportStartOut(BaseModel):
    export_task_id: str
    status: str
    mode: str


class ExportRequest(BaseModel):
    video_project_id: str
    export_format: str = "mp4"


# ============================================================
# 分镜拼接（独立于视频工程：直接选多个视频素材按顺序拼接）
# ============================================================

CONCAT_TRANSITIONS = {"none", "fade", "crossfade", "black", "white", "slide_right", "tech_mask"}


class ConcatItemIn(BaseModel):
    asset_id: str
    # 作用于该片段与下一片段之间的转场；最后一个片段的转场设置被忽略
    transition_type: str = "none"
    transition_duration: float = Field(default=0.5, ge=0.1, le=2.0)


class ConcatCreateIn(BaseModel):
    name: str | None = None
    items: list[ConcatItemIn] = Field(min_length=2)
    width: int = Field(default=1920, ge=320, le=7680)
    height: int = Field(default=1080, ge=240, le=4320)
    fps: int = 25


class ConcatTaskOut(TimestampedModel):
    project_id: str | None
    status: str
    progress: int
    output_key: str | None
    output_url: str | None
    file_size: int
    duration_seconds: float | None
    error_message: str | None
    params: dict | None


# ============================================================
# 自定义合成（不绑定分镜：自选视频 + 自输字幕/TTS 直接合成）
# ============================================================

CUSTOM_SEGMENT_AUDIO_MODES = {"mute", "keep_original", "tts"}
CUSTOM_SEGMENT_TIME_ADAPTATIONS = {"natural", "safe_stretch", "rife", "loop", "freeze", "trim"}
CUSTOM_SEGMENT_FIT_MODES = {"cover", "contain", "fill", "blur"}


class CustomSegmentIn(BaseModel):
    name: str | None = None
    visual_asset_id: str
    # 缺省时：TTS 模式按文本估算朗读时长，否则取素材自身时长
    duration: float | None = Field(default=None, ge=0.5, le=120.0)
    time_adaptation: str = "natural"
    fit_mode: str = "cover"
    subtitle_text: str | None = None
    audio_mode: str = "mute"  # mute | keep_original | tts
    voice_template_id: str | None = None
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    width: int = Field(default=1920, ge=320, le=7680)
    height: int = Field(default=1080, ge=240, le=4320)
    fps: int = 25


class ExportTaskOut(TimestampedModel):
    video_project_id: str | None
    project_id: str | None
    export_format: str
    mode: str
    status: str
    progress: int
    attempts: int
    output_key: str | None
    output_url: str | None
    srt_key: str | None
    srt_url: str | None
    report_key: str | None
    report_url: str | None
    file_size: int
    duration_seconds: float | None
    error_message: str | None
    timeline_snapshot: dict | None
