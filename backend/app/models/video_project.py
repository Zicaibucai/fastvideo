"""VideoProject 视频工程模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class VideoProject(BaseModel):
    __tablename__ = "video_projects"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False, index=True
    )  # draft | composing | success | failed

    width: Mapped[int] = mapped_column(default=1920, nullable=False)
    height: Mapped[int] = mapped_column(default=1080, nullable=False)
    fps: Mapped[int] = mapped_column(default=24, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)

    # 分镜顺序快照 [{shot_id, sequence, duration, transition_type, transition_duration}]
    timeline: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Phase 5：多轨配置
    subtitle_style: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [{asset_id, name, volume, fade_in, fade_out, loop, authorization_status, authorization_note}]
    music_tracks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # {asset_id, position, size, opacity}
    logo_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {text, sub_text, music_asset_id, duration, brand_color}
    open_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {text, duration}
    close_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    brand_color: Mapped[str] = mapped_column(String(16), default="#1E3A5F", nullable=False)
    # 导出模式：demo | formal
    export_mode: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    # 最近一次导出的时间轴快照（历史成片可追溯）
    timeline_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 输出
    output_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    watermark_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project = relationship("Project", back_populates="video_projects")
    export_tasks = relationship(
        "ExportTask", back_populates="video_project", cascade="all, delete-orphan"
    )
    segments = relationship(
        "VideoSegment",
        back_populates="video_project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="VideoSegment.sequence",
    )
