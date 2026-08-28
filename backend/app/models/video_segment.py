"""VideoSegment 视频分段模型（Phase 5）。

每个视频工程下，一条分镜对应一个视频分段。
分段负责：画面来源、时长、运动、适配、转场、字幕、音量、渲染状态与缓存。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class VideoSegment(BaseModel):
    __tablename__ = "video_segments"

    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    storyboard_shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="SET NULL"), index=True, nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 素材选择：只保存视频工程中显式选择的图片/视频；不从分镜或 AI 任务自动继承。
    visual_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    audio_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 时长（秒）
    duration: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    # natural 保持原始速度；safe_stretch 仅在安全范围内拉伸；rife 为严格 RIFE 补帧；
    # interpolate 为用户主动选择的 FFmpeg 补帧；loop/freeze 为短视频兜底。
    time_adaptation: Mapped[str | None] = mapped_column(String(24), default="natural", nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 画面（visual_motion 为旧库兼容字段，视频工程不再暴露或使用）
    visual_motion: Mapped[str] = mapped_column(
        String(24), default="zoom_in", nullable=False
    )  # static | zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down
    fit_mode: Mapped[str] = mapped_column(
        String(16), default="cover", nullable=False
    )  # cover | contain | fill | blur

    # 转场
    transition_type: Mapped[str] = mapped_column(
        String(24), default="crossfade", nullable=False
    )  # none | fade | crossfade | black | white | slide_left | slide_right | tech_mask
    transition_duration: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    # 字幕 / 音量
    subtitle_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # 渲染状态
    render_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )  # pending | queued | running | success | failed | skipped
    render_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    needs_rebuild: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 乐观锁版本号（并发编辑保护）
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")

    video_project = relationship("VideoProject", back_populates="segments")
    storyboard_shot = relationship("StoryboardShot", lazy="selectin")
