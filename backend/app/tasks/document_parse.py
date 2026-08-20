"""招标资料解析任务：按页解析 PDF/DOCX/TXT + 表格提取 + 扫描页 OCR 降级。

解析流程：
1. 读取文件字节
2. 调用 document_parser 逐页解析（含 OCR 降级）
3. 写入 DocumentPage / DocumentChunk（禁止整篇正文存单字段）
4. 调用 fact_extractor 提取工程参数（含来源页码、冲突检测）
5. 若文档为评分办法，调用 scoring_service 提取评分点
"""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.document_chunk import DocumentChunk
from app.models.document_page import DocumentPage
from app.models.render_task import RenderTask
from app.models.source_document import SourceDocument
from app.services.document_parser import parse_document_bytes
from app.services.fact_extractor import (
    apply_conflicts,
    extract_facts_from_pages,
    sync_project_key_params,
)
from app.services.scoring_service import extract_scoring_points
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def _parse_document(params: dict[str, Any]) -> dict[str, Any]:
    doc_id = params["doc_id"]
    db = SessionLocal()
    try:
        doc = db.get(SourceDocument, doc_id)
        if not doc:
            raise RuntimeError("文档不存在")

        doc.parse_status = "parsing"
        doc.parse_error = None
        db.commit()

        raw_bytes = storage.load(doc.file_key)

        # 1. 逐页解析
        parsed = parse_document_bytes(raw_bytes, doc.file_type)

        # 2. 清空旧的 pages/chunks 记录（重新解析）
        db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).delete()
        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
        db.flush()

        # 3. 写入页面
        for p in parsed.pages:
            db.add(
                DocumentPage(
                    document_id=doc.id,
                    page_number=p.page_number,
                    location_label=p.location_label,
                    raw_text=p.raw_text,
                    cleaned_text=p.cleaned_text,
                    markdown_text=p.markdown_text,
                    page_type=p.page_type,
                    extraction_method=p.extraction_method,
                    ocr_status=p.ocr_status,
                    confidence=p.confidence,
                    metadata_json=p.metadata,
                )
            )

        # 4. 写入内容块
        for c in parsed.chunks:
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    heading_path=c.heading_path,
                    content=c.content,
                    token_count=len(c.content or "") // 1,
                    chunk_type=c.chunk_type,
                    metadata_json=c.metadata,
                )
            )

        # 更新文档统计字段
        doc.page_count = parsed.total_pages
        doc.total_pages = parsed.total_pages
        doc.ocr_pages = parsed.ocr_pages
        doc.failed_pages = parsed.failed_pages
        doc.table_count = parsed.table_count

        # 兼容旧字段（保留 short text）
        doc.full_text = "\n".join(
            f"[{p.location_label}] {p.cleaned_text[:200]}"
            for p in parsed.pages
            if p.cleaned_text
        )[:50_000]
        doc.page_anchors = {
            str(p.page_number): (p.cleaned_text or "")[:300]
            for p in parsed.pages
            if p.cleaned_text
        }

        # 5. 提取工程参数 → ExtractedFact
        # 先清理该项目该文档的旧事实
        from app.models.extracted_fact import ExtractedFact

        db.query(ExtractedFact).filter(
            ExtractedFact.document_id == doc.id
        ).delete()
        db.flush()

        candidates = extract_facts_from_pages(parsed.pages, doc.id, doc.project_id)
        fact_objs = []
        for c in candidates:
            f = ExtractedFact(**c)
            db.add(f)
            fact_objs.append(f)
        db.flush()

        # 冲突检测：对该项目全部事实重新检测（含其它文档）
        all_facts = (
            db.query(ExtractedFact)
            .filter(ExtractedFact.project_id == doc.project_id)
            .all()
        )
        apply_conflicts(db, all_facts)

        # 6. 评分办法 → 评分点（提取逻辑要求同时命中"评分项关键词"和"分值"，安全）
        scoring_count = extract_scoring_points(db, doc.id, doc.project_id, parsed.pages)

        doc.parse_status = "success"
        doc.parse_error = None
        db.commit()

        return {
            "doc_id": doc_id,
            "status": "success",
            "page_count": parsed.total_pages,
            "ocr_pages": parsed.ocr_pages,
            "failed_pages": parsed.failed_pages,
            "table_count": parsed.table_count,
            "fact_count": len(fact_objs),
            "conflict_count": sum(1 for f in fact_objs if f.verification_status == "conflict"),
            "scoring_count": scoring_count,
        }
    except Exception as exc:
        db.refresh(doc)
        doc.parse_status = "failed"
        doc.parse_error = str(exc)[:2000]
        db.commit()
        logger.exception("parse_document_failed", doc_id=doc_id)
        raise
    finally:
        db.close()


# ---------------- Celery 任务 ----------------

@celery_app.task(bind=True, name="fastvideo.parse_document", max_retries=3, default_retry_delay=10)
def parse_document_task(self, task_id: str) -> dict:
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError("任务不存在")
        task.status = "running"
        task.attempts += 1
        db.commit()
    finally:
        db.close()
    try:
        return _parse_document_from_db(task_id)
    except Exception as exc:
        db = SessionLocal()
        try:
            t = db.get(RenderTask, task_id)
            if t:
                t.status = "failed"
                t.error_message = str(exc)[:2000]
                t.message = "文档解析失败"
                db.commit()
        finally:
            db.close()
        raise self.retry(exc=exc) from exc


def _parse_document_from_db(task_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError("任务不存在")
        result = _parse_document(task.params or {})
        db.refresh(task)
        task.status = "success"
        task.progress = 100
        task.result = result
        task.message = "文档解析完成"
        db.commit()
        return result
    finally:
        db.close()


parse_document_sync = _parse_document
