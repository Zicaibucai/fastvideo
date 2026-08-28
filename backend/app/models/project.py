"""Project 投标项目模型。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Project(BaseModel):
    __tablename__ = "projects"

    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 招标编号
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False, index=True
    )  # draft | active | archived
    last_entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # 关键投标参数（含来源页码，防止 AI 编造）
    bid_area: Mapped[float | None] = mapped_column(Float, nullable=True)  # 建筑面积(m²)
    area_source_page: Mapped[int | None] = mapped_column(nullable=True)
    bid_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_source_page: Mapped[int | None] = mapped_column(nullable=True)
    construction_period: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 工期
    period_source_page: Mapped[int | None] = mapped_column(nullable=True)
    bidder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 招标人
    bidder_source_page: Mapped[int | None] = mapped_column(nullable=True)

    # 技术参数摘要（结构化 {名称: {value, page}}）
    tech_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 协作审核策略：disabled（不启用）| recommended（建议，不阻断）| required（正式导出强制）
    review_policy: Mapped[str] = mapped_column(
        String(16), default="recommended", nullable=False, server_default="recommended"
    )
    # 乐观锁版本号：更新接口校验 base_revision，不一致返回 409
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")

    owner = relationship("User", back_populates="projects")
    members = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
    source_documents = relationship(
        "SourceDocument", back_populates="project", cascade="all, delete-orphan"
    )
    storyboard_shots = relationship(
        "StoryboardShot", back_populates="project", cascade="all, delete-orphan"
    )
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
    render_tasks = relationship(
        "RenderTask", back_populates="project", cascade="all, delete-orphan"
    )
    voice_templates = relationship(
        "VoiceTemplate", back_populates="project", cascade="all, delete-orphan"
    )
    video_projects = relationship(
        "VideoProject", back_populates="project", cascade="all, delete-orphan"
    )
    facts = relationship("ExtractedFact", back_populates="project", cascade="all, delete-orphan")
    scoring_points = relationship(
        "ScoringPoint", back_populates="project", cascade="all, delete-orphan"
    )
    render_jobs = relationship("RenderJob", back_populates="project", cascade="all, delete-orphan")
