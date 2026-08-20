"""StoryboardShot 解说词与分镜模型。

每个分镜对应一段解说词 + 画面 + 配音音频 + 输出视频片段。
AI 结果支持多版本（versions JSON）与人工编辑。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class StoryboardShot(BaseModel):
    __tablename__ = "storyboard_shots"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 分镜序号
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 分镜标题
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 章节（片头/正文/片尾）

    # 解说词
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)  # 预计时长
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 来源页码

    # 解说词变化追踪（Phase 4）
    narration_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    narration_prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    narration_updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 画面
    visual_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # title|model_image|site_photo|generated_image|generated_video|bim_animation|infographic
    visual_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    visual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)

    image_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    video_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    # 画面制作关联（Phase 3）
    source_model_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    render_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # none|generating|reviewing|approved|rejected
    visual_review_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 选择历史 [{version_id, asset_id, selected_by, selected_at}]
    visual_history: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 音频 / 视频
    tts_voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    video_clip_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # 来源引用与事实校验
    # [{documentId, documentName, page, locationLabel, quote}]
    source_references: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scoring_point_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # verified | partial | unverified | conflict
    fact_check_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False, index=True
    )  # draft | ai_generating | ai_done | edited | failed

    # 历史版本（[{revision, narration, visual_prompt, created_at, source}]）
    versions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    project = relationship("Project", back_populates="storyboard_shots")
    image_asset = relationship("Asset", foreign_keys=[image_asset_id], lazy="selectin")
    video_asset = relationship("Asset", foreign_keys=[video_asset_id], lazy="selectin")
    audio_asset = relationship("Asset", foreign_keys=[audio_asset_id], lazy="selectin")
