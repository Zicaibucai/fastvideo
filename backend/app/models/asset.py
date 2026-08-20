"""Asset 素材模型：图片、视频、音频、模型截图等。"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Asset(BaseModel):
    __tablename__ = "assets"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # image | video | audio | model | document
    source: Mapped[str] = mapped_column(
        String(32), default="upload", nullable=False
    )  # upload | ai_image | ai_video | ai_tts | model_shot | render
    file_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 兼容外链
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)

    # 文件校验与元数据
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    thumbnail_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    color_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_original_model_shot: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_software: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    camera_angle: Mapped[str | None] = mapped_column(String(32), nullable=True)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_conceptual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_disclaimer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 生成信息
    generated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)

    project = relationship("Project", back_populates="assets")

    # 被分镜引用的反向关系（不级联删除，仅用于查询）
    shot_as_image = relationship(
        "StoryboardShot",
        foreign_keys="StoryboardShot.image_asset_id",
        lazy="noload",
        viewonly=True,
        overlaps="image_asset",
    )
    shot_as_video = relationship(
        "StoryboardShot",
        foreign_keys="StoryboardShot.video_asset_id",
        lazy="noload",
        viewonly=True,
        overlaps="video_asset",
    )
    shot_as_audio = relationship(
        "StoryboardShot",
        foreign_keys="StoryboardShot.audio_asset_id",
        lazy="noload",
        viewonly=True,
        overlaps="audio_asset",
    )
