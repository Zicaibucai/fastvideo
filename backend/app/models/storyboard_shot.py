"""StoryboardShot 解说词与分镜模型。

分镜保存叙事、时长和来源信息；画面渲染结果属于独立素材库，视频素材只在
AI 视频/视频工程链路中按需使用。AI 结果支持多版本（versions JSON）与人工编辑。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.status import StatusValidationMixin, StoryboardShotStatus


class StoryboardShot(StatusValidationMixin, BaseModel):
    __tablename__ = "storyboard_shots"
    VALID_STATUSES = frozenset(item.value for item in StoryboardShotStatus)

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

    video_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    # 画面制作（模型截图渲染）绑定。与 AI 视频素材分开，AI 视频不会写入这些字段。
    source_model_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    render_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    visual_review_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
        String(32), default=StoryboardShotStatus.DRAFT.value, nullable=False, index=True
    )  # draft | ai_generating | ai_done | edited | failed

    # 分镜身份必须跨重生成保持稳定。旧版本不再删除，而是归档，供视频工程与素材绑定追溯。
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 历史版本（[{revision, narration, visual_prompt, created_at, source}]）
    versions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    project = relationship("Project", back_populates="storyboard_shots")
    narration_beats = relationship(
        "NarrationBeat", back_populates="shot", cascade="all, delete-orphan", order_by="NarrationBeat.sequence"
    )
    video_asset = relationship("Asset", foreign_keys=[video_asset_id], lazy="selectin")
    audio_asset = relationship("Asset", foreign_keys=[audio_asset_id], lazy="selectin")
