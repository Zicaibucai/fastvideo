"""阅读器 / 页面 / 分块 / 参数 / 评分点 Schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel


# ---------- DocumentPage ----------
class DocumentPageOut(TimestampedModel):
    document_id: str
    page_number: int
    location_label: str | None
    raw_text: str | None
    cleaned_text: str | None
    markdown_text: str | None
    page_type: str
    extraction_method: str
    ocr_status: str
    confidence: float | None
    metadata_json: dict | None


class DocumentPageContent(DocumentPageOut):
    tables: list[dict] | None = None  # 该页表格（结构化 JSON）


# ---------- DocumentChunk ----------
class DocumentChunkOut(TimestampedModel):
    document_id: str
    sequence: int = 0
    page_start: int | None
    page_end: int | None
    heading_path: str | None
    content: str | None
    token_count: int
    chunk_type: str
    metadata_json: dict | None


# ---------- 目录 / 搜索 ----------
class DocumentTocItem(BaseModel):
    heading_path: str
    heading_text: str
    level: int
    page: int | None
    page_start: int | None
    page_end: int | None


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    page: int | None
    location_label: str | None
    heading_path: str | None
    content: str
    highlight: str | None = None


# ---------- ExtractedFact ----------
FactVerificationStatus = Literal["unverified", "confirmed", "rejected", "conflict"]


class ExtractedFactOut(TimestampedModel):
    project_id: str
    document_id: str | None
    document_name: str | None = None
    page_number: int | None
    source_order: int | None = None
    location_label: str | None
    fact_type: str
    fact_name: str
    fact_label: str
    fact_value: str
    scope: str | None = None
    category: str | None = None
    usage_status: str = "review"
    unit: str | None
    source_quote: str | None
    confidence: float
    verification_status: str
    confirmed_by: str | None
    confirmed_at: str | None
    candidates: list | None


class FactConfirmRequest(BaseModel):
    status: FactVerificationStatus = Field(..., description="confirmed / rejected / unverified")
    fact_value: str | None = None  # 人工修改后的值
    unit: str | None = None
    note: str | None = None


class FactConfirmResult(BaseModel):
    id: str
    status: str
    message: str


# ---------- ScoringPoint ----------
class ScoringPointOut(TimestampedModel):
    project_id: str
    title: str
    description: str | None
    score: float | None
    score_total: float | None
    source_document_id: str | None
    source_page: int | None
    source_quote: str | None
    matched_shot_ids: list | None
    category: str | None


class ScoringCoverage(BaseModel):
    total: int
    covered: int
    coverage_rate: float  # 0-1
    points: list[ScoringPointOut]
