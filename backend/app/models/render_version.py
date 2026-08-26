"""RenderVersion 渲染结果版本模型。

原图永远作为 V0；生成结果从 V1 开始。不覆盖旧版本。
删除采用软删除（is_deleted）或引用检查。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class RenderVersion(BaseModel):
    __tablename__ = "render_versions"
    __table_args__ = (
        UniqueConstraint("render_job_id", "version_number", name="uq_render_versions_job_version"),
    )

    render_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    source_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_type: Mapped[str] = mapped_column(String(16), default="render", nullable=False)

    # 提示词快照
    prompt_snapshot: Mapped[str | None] = mapped_column(JSON, nullable=True)
    negative_prompt_snapshot: Mapped[str | None] = mapped_column(JSON, nullable=True)
    parameter_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 质量指标（结构一致性辅助检查）
    quality_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )  # pending|passed|warning|failed

    # 选择状态
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 软删除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    render_job = relationship("RenderJob", back_populates="versions")
    result_asset = relationship("Asset", foreign_keys=[result_asset_id], lazy="selectin")
