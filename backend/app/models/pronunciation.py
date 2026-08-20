"""PronunciationProfile 发音词典 / PronunciationRule 发音规则模型。

发音规则用于把解说词中的数字、单位、缩写、企业名称等
转换为可准确朗读的文本（朗读文本），不影响原始解说词。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class PronunciationProfile(BaseModel):
    __tablename__ = "pronunciation_profiles"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)

    # system | enterprise | project
    scope: Mapped[str] = mapped_column(String(16), default="project", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    rules = relationship(
        "PronunciationRule",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PronunciationRule(BaseModel):
    __tablename__ = "pronunciation_rules"

    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("pronunciation_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )

    source_text: Mapped[str] = mapped_column(String(500), nullable=False)
    spoken_text: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)

    # literal | number | unit | abbreviation | company | custom
    rule_type: Mapped[str] = mapped_column(String(16), default="literal", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # system | enterprise | project
    scope: Mapped[str] = mapped_column(String(16), default="project", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 冲突提示（与更高优先级规则冲突时）
    conflict_hint: Mapped[str | None] = mapped_column(Text, nullable=True)

    profile = relationship("PronunciationProfile", back_populates="rules")
