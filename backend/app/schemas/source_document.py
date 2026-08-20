"""招标资料 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel


class SourceDocumentOut(TimestampedModel):
    project_id: str
    file_name: str
    file_key: str
    file_type: str
    file_size: int
    page_count: int | None
    title: str | None
    doc_type: str
    parse_status: str
    parse_error: str | None
    extracted_params: dict | None
    sha256: str | None
    mime_type: str | None
    is_duplicate: bool = False
    original_document_id: str | None
    total_pages: int | None
    ocr_pages: int = 0
    failed_pages: int = 0
    table_count: int = 0


class SourceDocumentParseResult(BaseModel):
    doc_id: str
    status: str
    message: str
    page_count: int | None = None
    extracted_params: dict | None = None


class SourceDocumentUpdate(BaseModel):
    title: str | None = None
    doc_type: str | None = None


class ParseParamsRequest(BaseModel):
    """人工确认/修正文档关键参数。"""

    params: dict = Field(..., description="关键参数，例如 {'bid_area': {'value': 12345, 'page': 3}}")


class ResumableUploadInitRequest(BaseModel):
    """创建大文件分片上传会话。"""

    file_name: str = Field(..., min_length=1, max_length=512)
    file_size: int = Field(..., gt=0)
    doc_type: str = "tender"


class ResumableUploadOut(BaseModel):
    id: str
    file_name: str
    file_size: int
    chunk_size: int
    total_chunks: int
    uploaded_chunks: list[int]
    uploaded_bytes: int
    progress: int
    status: str
    document_id: str | None = None
    error_message: str | None = None
