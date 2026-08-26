"""RenderJob 渲染任务模型。

一次渲染任务可产生多个版本（RenderVersion）。任务支持
render/inpaint/outpaint/upscale 四种操作，含成本与进度跟踪。
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class RenderJob(BaseModel):
    __tablename__ = "render_jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_render_jobs_project_idempotency"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), index=True, nullable=True
    )
    preset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 操作类型 render|inpaint|outpaint|upscale|color_grade
    operation_type: Mapped[str] = mapped_column(String(16), default="render", nullable=False)

    # 提示词
    positive_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 渲染参数
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="16:9", nullable=False)
    output_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variant_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    structure_strength: Mapped[int] = mapped_column(Integer, default=85, nullable=False)
    creativity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 保留项（布尔：是否保留）
    preserve_logo: Mapped[bool] = mapped_column(default=True, nullable=False)
    preserve_text: Mapped[bool] = mapped_column(default=True, nullable=False)
    preserve_roads: Mapped[bool] = mapped_column(default=True, nullable=False)
    preserve_building_shape: Mapped[bool] = mapped_column(default=True, nullable=False)
    preserve_equipment: Mapped[bool] = mapped_column(default=True, nullable=False)
    custom_constraints: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 遮罩（局部重绘用）
    mask_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 任务状态
    status: Mapped[str] = mapped_column(
        String(16), default="queued", nullable=False, index=True
    )  # queued|running|success|failed|cancelled
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 幂等键
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Provider 任务
    provider_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 成本
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)

    # 时间戳
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 概念创意图标记（用户请求与工程事实冲突时）
    is_conceptual: Mapped[bool] = mapped_column(default=False, nullable=False)
    concept_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project")
    source_asset = relationship("Asset", foreign_keys=[source_asset_id], lazy="selectin")
    versions = relationship(
        "RenderVersion",
        back_populates="render_job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_summary_dict(self) -> dict:
        from datetime import datetime

        return {
            "id": self.id,
            "operation_type": self.operation_type,
            "status": self.status,
            "progress": self.progress,
            "provider": self.provider,
            "model_name": self.model_name,
            "seed": self.seed,
            "aspect_ratio": self.aspect_ratio,
            "structure_strength": self.structure_strength,
            "variant_count": self.variant_count,
            "error_message": self.error_message,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
            "currency": self.currency,
            "is_conceptual": self.is_conceptual,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "version_count": len(self.versions),
        }
