"""SourceDocument 招标资料模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class SourceDocument(BaseModel):
    __tablename__ = "source_documents"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_key: Mapped[str] = mapped_column(String(1024), nullable=False)  # 存储 key
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # pdf | docx | txt | image | other
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    doc_type: Mapped[str] = mapped_column(
        String(32), default="tender", nullable=False, index=True
    )  # tender 招标文件 | scoring 评分办法 | construction 施工组织设计 | profile 项目概况 | schedule 进度计划 | special 专项方案 | qualification 企业资信 | other 其他

    # 文件校验
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    original_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 解析状态
    parse_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )  # pending | queued | parsing | ocr | success | failed
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 解析统计
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 全文解析结果与关键参数（含来源页码）——保留兼容旧字段，正文改存 DocumentPage
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    page_anchors: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {页码: 片段}

    project = relationship("Project", back_populates="source_documents")
    pages = relationship(
        "DocumentPage", back_populates="document", cascade="all, delete-orphan"
    )
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    facts = relationship("ExtractedFact", back_populates="document")
    scoring_points = relationship("ScoringPoint", back_populates="source_document")
