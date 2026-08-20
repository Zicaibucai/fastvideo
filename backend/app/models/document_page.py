"""DocumentPage 文档页面模型。

每页一个记录，保存原始文本/清洗文本/Markdown 文本及提取方式。
禁止将整份文档正文保存在单一字段，必须按页管理。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class DocumentPage(BaseModel):
    __tablename__ = "document_pages"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 页码或段落位置标签（如 "P3" / "段落 12"）
    location_label: Mapped[str] = mapped_column(String(64), nullable=True)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # text | table | scan | mixed
    page_type: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    # native | ocr | mixed
    extraction_method: Mapped[str] = mapped_column(String(16), default="native", nullable=False)

    ocr_status: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False
    )  # none | pending | running | success | failed
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    document = relationship("SourceDocument", back_populates="pages")
