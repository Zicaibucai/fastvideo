"""解说词长文证据索引运行记录。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class NarrationRun(BaseModel):
    __tablename__ = "narration_runs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False, index=True)
    generation_mode: Mapped[str] = mapped_column(String(32), default="multi_stage", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), default="evidence-v1", nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_batches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_batches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project")
    batches = relationship("NarrationEvidenceBatch", back_populates="run", cascade="all, delete-orphan")
    evidence = relationship("NarrationEvidence", back_populates="run", cascade="all, delete-orphan")


class NarrationEvidenceBatch(BaseModel):
    __tablename__ = "narration_evidence_batches"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("narration_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_start_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_end_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cache_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    content_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run = relationship("NarrationRun", back_populates="batches")
    document = relationship("SourceDocument")
    evidence = relationship("NarrationEvidence", back_populates="batch", cascade="all, delete-orphan")


class NarrationEvidence(BaseModel):
    __tablename__ = "narration_evidence"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("narration_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("narration_evidence_batches.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[list | None] = mapped_column(JSON, nullable=True)
    construction_actions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sequence_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fact_check_status: Mapped[str] = mapped_column(String(16), default="partial", nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    run = relationship("NarrationRun", back_populates="evidence")
    batch = relationship("NarrationEvidenceBatch", back_populates="evidence")
    project = relationship("Project")
    document = relationship("SourceDocument")
