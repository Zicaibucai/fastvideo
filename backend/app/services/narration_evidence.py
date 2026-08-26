"""长文档解说词证据索引。

这层故意不生成普通 prose 摘要，而是把全文转换成可引用的工程事实。
这样后续大纲和旁白可以按专题检索，同时保留数字、工序和来源块。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field, model_validator

from app.core.logging import get_logger
from app.models.document_chunk import DocumentChunk
from app.models.narration_run import NarrationEvidence, NarrationEvidenceBatch, NarrationRun
from app.models.source_document import SourceDocument

logger = get_logger(__name__)

EVIDENCE_TOPICS = [
    "项目概况", "总体部署", "工期节点", "平面及垂直运输", "基坑土方",
    "重点工艺", "钢结构", "机电", "BIM", "质量安全", "绿色施工", "总承包管理",
]
EVIDENCE_PROMPT_VERSION = "evidence-v2"


class MappedEvidence(BaseModel):
    topic: str = "项目概况"
    fact: str = ""
    parameters: list[str] = Field(default_factory=list)
    constructionActions: list[str] = Field(default_factory=list)
    sequenceContext: str = ""
    sourceChunkIds: list[str] = Field(default_factory=list)
    sourceReference: dict[str, Any] = Field(default_factory=dict)
    factCheckStatus: str = "partial"

    @model_validator(mode="before")
    @classmethod
    def normalise_nullable_fields(cls, value: Any) -> Any:
        """Accept common JSON nulls while keeping the persisted shape stable."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if data.get("topic") is None:
            data["topic"] = "项目概况"
        if data.get("fact") is None:
            data["fact"] = ""
        if data.get("sequenceContext") is None:
            data["sequenceContext"] = ""
        if data.get("factCheckStatus") is None:
            data["factCheckStatus"] = "partial"
        for key in ("parameters", "constructionActions", "sourceChunkIds"):
            raw_items = data.get(key)
            if raw_items is None:
                data[key] = []
            elif not isinstance(raw_items, list):
                data[key] = [str(raw_items)]
            else:
                data[key] = [str(item) for item in raw_items if item is not None]
        if data.get("sourceReference") is None or not isinstance(data.get("sourceReference"), dict):
            data["sourceReference"] = {}
        return data


class MappedEvidenceOutput(BaseModel):
    evidenceItems: list[MappedEvidence] = Field(default_factory=list)
    rejectedFacts: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalise_nullable_output(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if data.get("evidenceItems") is None:
            data["evidenceItems"] = []
        rejected = data.get("rejectedFacts")
        if rejected is None:
            data["rejectedFacts"] = []
        elif not isinstance(rejected, list):
            data["rejectedFacts"] = [str(rejected)]
        else:
            data["rejectedFacts"] = [str(item) for item in rejected if item is not None]
        return data


@dataclass
class EvidenceBatchInput:
    document: SourceDocument
    index: int
    chunk_ids: list[str]
    start_sequence: int
    end_sequence: int
    content: str


def _clean(text: str | None, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _json_from_model(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            candidate = raw[start : end + 1]
            json.loads(candidate)
            return candidate
    raise ValueError("证据批次未返回合法JSON")


def _document_batches(db, project_id: str, batch_size_chars: int = 9000) -> list[EvidenceBatchInput]:
    """按文档和稳定chunk序号组合全文批次。"""
    documents = (
        db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id, SourceDocument.parse_status == "success")
        .order_by(SourceDocument.created_at.asc(), SourceDocument.id.asc())
        .all()
    )
    batches: list[EvidenceBatchInput] = []
    global_index = 0
    for document in documents:
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.sequence.asc(), DocumentChunk.created_at.asc(), DocumentChunk.id.asc())
            .all()
        )
        current: list[str] = []
        current_ids: list[str] = []
        start_sequence = 0
        end_sequence = 0

        def flush() -> None:
            nonlocal global_index, current, current_ids, start_sequence, end_sequence
            if not current:
                return
            global_index += 1
            batches.append(
                EvidenceBatchInput(
                    document=document,
                    index=global_index,
                    chunk_ids=list(current_ids),
                    start_sequence=start_sequence,
                    end_sequence=end_sequence,
                    content="\n".join(current),
                )
            )
            current = []
            current_ids = []
            start_sequence = 0
            end_sequence = 0

        for chunk in chunks:
            text = _clean(chunk.content, 5000)
            if not text:
                continue
            sequence = int(chunk.sequence or 0)
            marker = (
                f"【chunk:{chunk.id} seq:{sequence} "
                f"{chunk.metadata_json.get('location_label', '') if chunk.metadata_json else ''}】"
            )
            entry = f"{marker} {_clean(chunk.heading_path, 220)}\n{text}"
            if current and len("\n".join(current)) + len(entry) > batch_size_chars:
                flush()
            if not current:
                start_sequence = sequence
            current.append(entry)
            current_ids.append(chunk.id)
            end_sequence = sequence
        flush()
    return batches


def create_evidence_run(db, project_id: str, params: dict[str, Any]) -> NarrationRun:
    run = NarrationRun(
        project_id=project_id,
        status="evidence_extracting",
        generation_mode=params.get("generation_mode", "multi_stage"),
        prompt_version=EVIDENCE_PROMPT_VERSION,
        params=dict(params),
        progress={"stage": "evidence_extracting", "completed": 0, "total": 0},
    )
    db.add(run)
    db.flush()
    batches = _document_batches(db, project_id, int(params.get("evidence_batch_chars", 9000)))
    model = str(params.get("model") or params.get("llm_model") or "default")
    outline = str(params.get("predefined_outline") or "").strip()
    for batch in batches:
        digest = hashlib.sha256(batch.content.encode("utf-8")).hexdigest()
        cache_material = f"{digest}|{EVIDENCE_PROMPT_VERSION}|{model}"
        if outline:
            cache_material += "|outline:" + hashlib.sha256(outline.encode("utf-8")).hexdigest()
        cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
        current = NarrationEvidenceBatch(
            run_id=run.id,
            document_id=batch.document.id,
            batch_index=batch.index,
            chunk_start_sequence=batch.start_sequence,
            chunk_end_sequence=batch.end_sequence,
            chunk_ids=batch.chunk_ids,
            content_hash=digest,
            cache_key=cache_key,
            content_chars=len(batch.content),
            status="queued",
            attempts=0,
        )
        db.add(current)
        db.flush()

        # 同一份文档、同一版提示词和同一模型不重复消耗 API 配额。
        cached = (
            db.query(NarrationEvidenceBatch)
            .join(NarrationEvidenceBatch.run)
            .filter(
                NarrationEvidenceBatch.cache_key == cache_key,
                NarrationEvidenceBatch.status == "success",
                NarrationEvidenceBatch.id != current.id,
            )
            .order_by(NarrationEvidenceBatch.created_at.desc())
            .first()
        )
        if cached:
            current.status = "success"
            current.result = cached.result
            cached_rows = db.query(NarrationEvidence).filter(NarrationEvidence.batch_id == cached.id).all()
            for row in cached_rows:
                db.add(
                    NarrationEvidence(
                        run_id=run.id,
                        batch_id=current.id,
                        project_id=run.project_id,
                        document_id=current.document_id,
                        topic=row.topic,
                        fact=row.fact,
                        parameters=row.parameters,
                        construction_actions=row.construction_actions,
                        sequence_context=row.sequence_context,
                        source_reference=row.source_reference,
                        source_chunk_ids=row.source_chunk_ids,
                        fact_check_status=row.fact_check_status,
                        review_status="pending",
                        fingerprint=row.fingerprint,
                    )
                )
    run.total_batches = len(batches)
    run.progress = {"stage": "evidence_extracting", "completed": 0, "total": len(batches)}
    db.commit()
    db.refresh(run)
    return run


def _build_batch_prompt(
    batch: NarrationEvidenceBatch,
    content: str,
    document_name: str,
    predefined_outline: str = "",
) -> str:
    return f"""你是工程投标资料证据审查员。只分析资料，不写解说词。

文档：{document_name}
批次：{batch.batch_index}
专题：{"、".join(EVIDENCE_TOPICS)}

【用户预设解说词大纲】
{predefined_outline or "（未提供，按工程专题归类）"}

请从原文中提取能够支撑施工组织推演的事实。重点保留数字、日期、楼层、区域、设备型号、工程量、施工动作、前后工序和空间关系。

硬规则：
1. 只能使用下面原文，不得补写工程常识。
2. 每条事实必须带 sourceChunkIds，必须引用原文中出现的chunk标记。
3. 参数、设备、日期和施工方法必须保留原文写法。
4. 没有明确依据的内容放入 rejectedFacts。
5. 同一事实在本批次内只保留一次。
6. 只输出JSON，不输出解释或解说词。

原文批次：
{content}

JSON格式：
{{
  "evidenceItems": [
    {{
      "topic": "基坑土方",
      "fact": "原文事实短句",
      "parameters": ["10.1米", "10.7万方"],
      "constructionActions": ["分层开挖"],
      "sequenceContext": "前一道工序完成后进入下一工序",
      "sourceChunkIds": ["chunk-id"],
      "sourceReference": {{"page": 1, "locationLabel": "段落1", "quote": "原文短引文"}},
      "factCheckStatus": "verified|partial|conflict"
    }}
  ],
  "rejectedFacts": []
}}"""


def _fallback_reference(batch: NarrationEvidenceBatch, document: SourceDocument) -> dict[str, Any]:
    return {
        "documentId": document.id,
        "documentName": document.file_name,
        "page": None,
        "locationLabel": f"块{batch.chunk_start_sequence}-{batch.chunk_end_sequence}",
        "quote": "",
    }


def _fingerprint(item: MappedEvidence) -> str:
    raw = "|".join(
        [item.topic.strip(), item.fact.strip(), *sorted(p.strip() for p in item.parameters)]
    )
    return hashlib.sha256(re.sub(r"\s+", "", raw).encode("utf-8")).hexdigest()


def _complete_evidence_batch(adapter, prompt: str) -> MappedEvidenceOutput:
    # Dense technical tables can produce more than 5k output tokens. DeepSeek
    # then returns a syntactically truncated JSON object even in JSON mode.
    # Retry once with a larger budget and a concise-output reminder.
    attempts = [
        (12000, prompt),
        (
            20000,
            prompt
            + "\n\n上一次返回未通过结构校验。请重新输出完整JSON："
            + "可选字段没有内容时请使用空字符串或空数组，不要输出null；"
            + "fact和quote保留原意但尽量简短，不得遗漏独有数字、设备、工序或空间关系。",
        ),
    ]
    last_error: Exception | None = None
    for max_tokens, current_prompt in attempts:
        raw = adapter.complete(
            current_prompt,
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return MappedEvidenceOutput.model_validate(json.loads(_json_from_model(raw)))
        except Exception as exc:
            last_error = exc
            logger.warning(
                "narration_evidence_json_retry",
                max_tokens=max_tokens,
                response_chars=len(raw or ""),
                error=str(exc),
            )
    raise ValueError(f"证据批次连续返回无法使用的结构: {last_error}") from last_error


def _persist_mapped_evidence(
    db,
    run: NarrationRun,
    batch: NarrationEvidenceBatch,
    document: SourceDocument | None,
    chunks: list[DocumentChunk],
    parsed: MappedEvidenceOutput,
) -> None:
    batch.result = parsed.model_dump(mode="json")
    batch.status = "success"
    batch.error_message = None
    db.query(NarrationEvidence).filter(NarrationEvidence.batch_id == batch.id).delete()
    valid_chunk_ids = set(batch.chunk_ids or [])
    first_source_chunk = chunks[0] if chunks else None
    source_text = "\n".join(chunk.content or "" for chunk in chunks)
    source_numbers = {number.replace(",", "") for number in re.findall(r"\d[\d,.]*", source_text)}
    for item in parsed.evidenceItems:
        if not item.fact.strip():
            continue
        source_chunk_ids = [chunk_id for chunk_id in item.sourceChunkIds if chunk_id in valid_chunk_ids]
        # 模型没有引用本批次真实 chunk 时，不能把这条内容伪装成可追溯证据。
        if not source_chunk_ids:
            continue
        claimed_numbers = {
            number.replace(",", "")
            for number in re.findall(r"\d[\d,.]*", " ".join([item.fact, *item.parameters]))
        }
        if any(number not in source_numbers for number in claimed_numbers):
            continue
        reference = dict(item.sourceReference or {})
        if document:
            reference["documentId"] = document.id
            reference["documentName"] = document.file_name
        if not reference.get("locationLabel"):
            reference["locationLabel"] = (
                (first_source_chunk.metadata_json or {}).get("location_label")
                if first_source_chunk
                else None
            ) or f"块{batch.chunk_start_sequence}-{batch.chunk_end_sequence}"
        quote = str(reference.get("quote") or "").strip()
        if quote and quote not in source_text:
            reference["quote"] = _clean(source_text, 180)
        if first_source_chunk:
            reference["page"] = (
                None
                if (first_source_chunk.metadata_json or {}).get("is_virtual_page")
                else first_source_chunk.page_start
            )
        db.add(
            NarrationEvidence(
                run_id=run.id,
                batch_id=batch.id,
                project_id=run.project_id,
                document_id=batch.document_id,
                topic=item.topic if item.topic in EVIDENCE_TOPICS else "项目概况",
                fact=item.fact.strip(),
                parameters=item.parameters,
                construction_actions=item.constructionActions,
                sequence_context=item.sequenceContext,
                source_reference=reference or _fallback_reference(batch, document),
                source_chunk_ids=source_chunk_ids,
                fact_check_status=item.factCheckStatus if item.factCheckStatus in {"verified", "partial", "conflict"} else "partial",
                review_status="pending",
                fingerprint=_fingerprint(item),
            )
        )


def extract_evidence_run(
    db,
    run_id: str,
    adapter,
    *,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    run = db.get(NarrationRun, run_id)
    if not run:
        raise ValueError("证据运行不存在")
    batches = (
        db.query(NarrationEvidenceBatch)
        .filter(NarrationEvidenceBatch.run_id == run_id)
        .order_by(NarrationEvidenceBatch.batch_index.asc())
        .all()
    )
    completed = sum(1 for batch in batches if batch.status == "success")
    pending: list[tuple[NarrationEvidenceBatch, SourceDocument | None, list[DocumentChunk], str]] = []
    try:
        for batch in batches:
            if batch.status == "success":
                continue
            # A process interruption may leave untouched rows in `running`.
            # Normalize them first; only submitted rows are marked running below.
            batch.status = "queued"
            document = db.get(SourceDocument, batch.document_id)
            chunks = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.id.in_(batch.chunk_ids or []))
                .order_by(DocumentChunk.sequence.asc(), DocumentChunk.id.asc())
                .all()
            )
            content = "\n".join(
                f"【chunk:{chunk.id} seq:{chunk.sequence}】 {_clean(chunk.heading_path, 220)}\n{_clean(chunk.content, 5000)}"
                for chunk in chunks
            )
            predefined_outline = _clean((run.params or {}).get("predefined_outline"), 6000)
            pending.append(
                (
                    batch,
                    document,
                    chunks,
                    _build_batch_prompt(
                        batch,
                        content,
                        document.file_name if document else "未知文档",
                        predefined_outline,
                    ),
                )
            )
        db.commit()

        configured_concurrency = int((run.params or {}).get("evidence_concurrency", 3))
        concurrency = max(1, min(8, configured_concurrency))
        from concurrent.futures import ThreadPoolExecutor, as_completed

        for offset in range(0, len(pending), concurrency):
            window = pending[offset : offset + concurrency]
            for batch, _document, _chunks, _prompt in window:
                batch.status = "running"
                batch.attempts += 1
            db.commit()

            window_errors: list[str] = []
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {
                    executor.submit(_complete_evidence_batch, adapter, prompt): (batch, document, chunks)
                    for batch, document, chunks, prompt in window
                }
                for future in as_completed(futures):
                    batch, document, chunks = futures[future]
                    try:
                        parsed = future.result()
                        _persist_mapped_evidence(db, run, batch, document, chunks, parsed)
                    except Exception as exc:
                        batch.status = "failed"
                        batch.error_message = str(exc)[:2000]
                        window_errors.append(f"批次{batch.batch_index}: {exc}")
                        db.commit()
                        continue
                    completed += 1
                    run.completed_batches = completed
                    run.progress = {"stage": "evidence_extracting", "completed": completed, "total": len(batches)}
                    db.commit()
                    if progress_callback:
                        progress_callback(round(completed * 100 / max(1, len(batches))), f"已处理证据批次 {completed}/{len(batches)}")
            if window_errors:
                # Stop before submitting the next window, while retaining every
                # successful result from this one for a cheap resume.
                run.status = "evidence_failed"
                run.error_message = " | ".join(window_errors)[:2000]
                db.commit()
                raise RuntimeError(run.error_message)
    except Exception as exc:
        if run.status != "evidence_failed":
            run.status = "evidence_failed"
            run.error_message = str(exc)[:2000]
        run.status = "evidence_failed"
        run.error_message = str(exc)[:2000]
        db.commit()
        raise

    # 同一轮中跨批次的完全重复事实只保留一条，避免大纲被重复参数挤满。
    evidence_rows = (
        db.query(NarrationEvidence)
        .filter(NarrationEvidence.run_id == run.id)
        .order_by(NarrationEvidence.topic.asc(), NarrationEvidence.created_at.asc())
        .all()
    )
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for row in evidence_rows:
        if row.fingerprint in seen:
            duplicate_ids.append(row.id)
        else:
            seen.add(row.fingerprint)
    if duplicate_ids:
        db.query(NarrationEvidence).filter(NarrationEvidence.id.in_(duplicate_ids)).delete(synchronize_session=False)
    run.evidence_count = len(evidence_rows) - len(duplicate_ids)
    run.status = "evidence_review"
    run.progress = {"stage": "evidence_review", "completed": len(batches), "total": len(batches)}
    run.error_message = None
    db.commit()
    return {
        "run_id": run.id,
        "status": run.status,
        "total_batches": len(batches),
        "completed_batches": len(batches),
        "evidence_count": run.evidence_count,
    }


def approve_evidence(db, run_id: str, evidence_ids: list[str] | None = None) -> int:
    query = db.query(NarrationEvidence).filter(NarrationEvidence.run_id == run_id)
    if evidence_ids:
        query = query.filter(NarrationEvidence.id.in_(evidence_ids))
    rows = query.all()
    for row in rows:
        row.review_status = "approved"
    run = db.get(NarrationRun, run_id)
    if run and rows:
        run.status = "outline_review"
        from datetime import datetime, timezone

        run.approved_at = datetime.now(timezone.utc)
    db.commit()
    return len(rows)


def evidence_for_generation(db, run_id: str | None, *, auto_approve: bool = True) -> list[NarrationEvidence]:
    if not run_id:
        return []
    query = db.query(NarrationEvidence).filter(NarrationEvidence.run_id == run_id)
    if not auto_approve:
        query = query.filter(NarrationEvidence.review_status == "approved")
    return query.order_by(NarrationEvidence.topic.asc(), NarrationEvidence.created_at.asc()).all()
