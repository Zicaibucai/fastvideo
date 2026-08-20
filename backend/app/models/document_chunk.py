"""DocumentChunk 文档内容块模型。

按内容块（标题层级、段落、表格）切分文档，建立文件/页码/原文关联。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class DocumentChunk(BaseModel):
    __tablename__ = "document_chunks"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(String(512), nullable=True)  # "1 > 1.1 > 施工部署"
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # section | paragraph | table | heading
    chunk_type: Mapped[str] = mapped_column(String(16), default="paragraph", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    document = relationship("SourceDocument", back_populates="chunks")
