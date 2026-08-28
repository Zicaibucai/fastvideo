"""ExtractedFact 工程参数事实模型。

每个参数保存：值、单位、来源文件/页码/完整原文上下文、置信度、人工确认状态。
metadata_json 额外保存中文参数名、对象范围、类别、提取方式和自动使用状态。
不同来源冲突时标记 conflict，不自动选择。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ExtractedFact(BaseModel):
    __tablename__ = "extracted_facts"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # 完整句子或表格行
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)
    # unverified | confirmed | rejected | conflict
    verification_status: Mapped[str] = mapped_column(
        String(16), default="unverified", nullable=False, index=True
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 同一 fact_name 的候选值（conflict 时展示各来源）
    candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 乐观锁版本号（并发编辑保护）
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")

    project = relationship("Project")
    document = relationship("SourceDocument", lazy="selectin")
