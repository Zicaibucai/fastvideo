"""招标资料解析任务：按页解析 PDF/DOCX/TXT + 表格提取 + 扫描页 OCR 降级。

解析流程：
1. 读取文件字节
2. 调用 document_parser 逐页解析（含 OCR 降级）
3. 写入 DocumentPage / DocumentChunk（禁止整篇正文存单字段）
4. 调用 fact_extractor 提取工程参数（含来源页码、冲突检测）
5. 若文档为评分办法，调用 scoring_service 提取评分点
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.document_chunk import DocumentChunk
from app.models.document_page import DocumentPage
from app.models.render_task import RenderTask
from app.models.source_document import SourceDocument
from app.services.document_parser import ParsedDocument, ParsedPage, parse_document_bytes
from app.services.fact_extractor import (
    apply_conflicts,
    enrich_numeric_candidates_with_ai,
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

        # 重新整理台账时可以复用已经解析好的页面，避免 639MB DOCX 再次解压。
        # 正常上传/首次解析仍走完整文件解析；只有明确传入 reuse_parsed_pages 才复用。
        reuse_parsed_pages = bool(params.get("reuse_parsed_pages"))
        existing_pages = []
        if reuse_parsed_pages:
            existing_pages = (
                db.query(DocumentPage)
                .filter(DocumentPage.document_id == doc.id)
                .order_by(DocumentPage.page_number.asc())
                .all()
            )
        if existing_pages:
            parsed = ParsedDocument(
                pages=[
                    ParsedPage(
                        page_number=page.page_number,
                        location_label=page.location_label or f"P{page.page_number}",
                        raw_text=page.raw_text or "",
                        cleaned_text=page.cleaned_text or "",
                        markdown_text=page.markdown_text or page.cleaned_text or "",
                        page_type=page.page_type or "text",
                        extraction_method=page.extraction_method or "native",
                        ocr_status=page.ocr_status or "none",
                        confidence=page.confidence,
                        metadata=page.metadata_json or {},
                    )
                    for page in existing_pages
                ],
                chunks=[],
                toc=[],
                total_pages=len(existing_pages),
                ocr_pages=sum(1 for page in existing_pages if page.extraction_method == "ocr"),
                failed_pages=sum(1 for page in existing_pages if page.ocr_status == "failed"),
                table_count=doc.table_count or 0,
            )
        else:
            # 大文件友好：优先从磁盘路径流式解析，避免把 1GB 招标文件整文件读入内存导致 OOM。
            # local 存储直接返回真实路径；MinIO 会下载到临时文件，解析后通过 release_local_path 删除。
            from app.services.document_parser import parse_document_path

            local_path = storage.local_path(doc.file_key)
            try:
                parsed = parse_document_path(local_path, doc.file_type)
            finally:
                storage.release_local_path(local_path)

        if not existing_pages:
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
                        sequence=c.sequence,
                        page_start=c.page_start,
                        page_end=c.page_end,
                        heading_path=c.heading_path,
                        content=c.content,
                        token_count=_count_chunk_tokens(c.content or ""),
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
        # 先提交删除，释放 SQLite 写锁；AI 批量整理可能持续较久，不能让
        # 整个 AI 调用过程一直占着文档和台账的写事务。
        db.commit()

        candidates = extract_facts_from_pages(parsed.pages, doc.id, doc.project_id)
        # 规则层先完整保留数字证据，再由 AI 根据完整上下文补充中文参数名。
        # AI 服务不可用时由 fact_extractor 保留规则结果，不阻塞文档解析。
        candidates = enrich_numeric_candidates_with_ai(candidates)
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


def _count_chunk_tokens(text: str) -> int:
    """与解析器保持一致的轻量 token 估算，避免把字符数误报为 token 数。"""
    import re

    cjk = len(re.findall(r"[一-鿿]", text))
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    return max(1, int(cjk / 1.5 + words)) if text else 0


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
        params = dict(task.params or {})
    finally:
        # 不要把读取 RenderTask 的事务带进长时间的文档解析和 AI 调用。
        db.close()

    result = _parse_document(params)

    db = SessionLocal()
    try:
        task = db.get(RenderTask, task_id)
        if not task:
            raise RuntimeError("任务不存在")
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
