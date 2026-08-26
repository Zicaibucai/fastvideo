"""AudioVersion 配音音频版本模型。

每条分镜可生成多个配音版本（V1、V2…），不覆盖历史版本。
删除采用软删除（is_deleted）或引用检查。
解说词修改后，旧版本标记 is_stale=True，不物理删除。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class AudioVersion(BaseModel):
    __tablename__ = "audio_versions"
    __table_args__ = (
        UniqueConstraint("storyboard_shot_id", "version_number", name="uq_audio_versions_shot_version"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    storyboard_shot_id: Mapped[str] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="CASCADE"), index=True, nullable=False
    )
    voice_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 文本快照（生成时保存，防止模板修改影响历史版本）
    original_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    pronunciation_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    narration_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Provider 与参数快照
    provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    pitch: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pause_strength: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 时长
    target_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_difference: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_difference_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # duration_status: estimated | generating | matched | slightly_short | slightly_long
    #                | script_adjustment_required | failed
    duration_status: Mapped[str] = mapped_column(String(32), default="estimated", nullable=False)

    # 音频素材（wav + mp3 两个文件）
    audio_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    wav_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mp3_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 字幕与波形
    subtitle_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    waveform_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Provider 返回的原始元数据（不含密钥）
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 质量
    quality_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )  # pending|passed|warning|failed

    # 授权快照（生成时的模板授权状态）
    authorization_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Mock 标记
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 解说词变化追踪
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stale_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 选择状态
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 软删除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 成本
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)

    project = relationship("Project")
    storyboard_shot = relationship("StoryboardShot", lazy="selectin")
    audio_asset = relationship("Asset", foreign_keys=[audio_asset_id], lazy="selectin")
