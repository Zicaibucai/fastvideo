"""ScoringPoint 评分点模型。

从评分办法提取评分项及分值，并记录被哪些分镜覆盖。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ScoringPoint(BaseModel):
    __tablename__ = "scoring_points"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)
    score_total: Mapped[float | None] = mapped_column(nullable=True)  # 该评分项所属大项总分

    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    matched_shot_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [shot_id]
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)

    project = relationship("Project")
    source_document = relationship("SourceDocument", lazy="selectin")
