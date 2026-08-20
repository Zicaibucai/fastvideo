"""招标资料路由：上传（含 SHA-256 去重）、解析、参数确认、搜索、删除保护。"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.config import settings
from app.core.storage import storage
from app.models.document_upload_session import DocumentUploadSession
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.schemas.document import SearchResult
from app.schemas.source_document import (
    ParseParamsRequest,
    ResumableUploadInitRequest,
    ResumableUploadOut,
    SourceDocumentOut,
    SourceDocumentUpdate,
)
from app.services.document_parser import compute_sha256, get_all_doc_types
from app.services.task_runner import create_render_task, dispatch
from app.tasks.document_parse import parse_document_sync, parse_document_task

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["招标资料"])

ALLOWED_TYPES = {".pdf", ".docx", ".doc", ".txt"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def _get_owned_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def _safe_filename(name: str) -> str:
    """文件名安全处理：去掉路径分隔符与危险字符。"""
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c not in '<>:"|?*')
    return name.strip() or "未命名文件"


def _detect_real_type(filename: str, content: bytes) -> str:
    """校验扩展名与实际文件类型。"""
    ext = Path(filename).suffix.lower()
    # 检查魔数
    if content[:5] == b"%PDF-":
        return "pdf"
    if content[:2] == b"PK" and ext == ".docx":
        return "docx"
    if ext == ".txt":
        return "txt"
    if ext == ".doc":
        return "docx"  # 简化处理
    return "pdf" if ext == ".pdf" else ext.lstrip(".") or "other"


def _upload_out(session: DocumentUploadSession) -> ResumableUploadOut:
    uploaded = sorted(set(int(index) for index in (session.uploaded_chunks or [])))
    uploaded_bytes = min(session.file_size, len(uploaded) * session.chunk_size)
    if uploaded and uploaded[-1] == session.total_chunks - 1:
        uploaded_bytes = min(
            session.file_size,
            (len(uploaded) - 1) * session.chunk_size
            + (session.file_size - (session.total_chunks - 1) * session.chunk_size),
        )
    return ResumableUploadOut(
        id=session.id,
        file_name=session.file_name,
        file_size=session.file_size,
        chunk_size=session.chunk_size,
        total_chunks=session.total_chunks,
        uploaded_chunks=uploaded,
        uploaded_bytes=uploaded_bytes,
        progress=round(uploaded_bytes * 100 / session.file_size) if session.file_size else 0,
        status=session.status,
        document_id=session.document_id,
        error_message=session.error_message,
    )


def _get_owned_upload(
    db: Session, project_id: str, upload_id: str, user: User
) -> DocumentUploadSession:
    session = db.get(DocumentUploadSession, upload_id)
    if not session or session.project_id != project_id or session.user_id != user.id:
        raise NotFoundError("上传任务不存在")
    return session


def _chunk_path(session: DocumentUploadSession, chunk_index: int) -> Path:
    directory = Path(session.temp_dir).resolve()
    root = settings.resumable_upload_root.resolve()
    if not directory.is_relative_to(root):
        raise ConflictError("上传暂存路径无效")
    return directory / f"{chunk_index:06d}.part"


def _create_document(
    db: Session,
    *,
    project_id: str,
    original_name: str,
    real_type: str,
    doc_type: str,
    size: int,
    sha256: str,
    mime_type: str,
    file_key: str,
) -> SourceDocument:
    duplicate = (
        db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id, SourceDocument.sha256 == sha256)
        .first()
    )
    if duplicate:
        raise ConflictError(f"该文件已上传过（{duplicate.file_name}），避免重复上传")
    doc = SourceDocument(
        project_id=project_id,
        file_name=original_name,
        file_key=file_key,
        file_type=real_type,
        file_size=size,
        doc_type=doc_type if doc_type in get_all_doc_types() else "other",
        parse_status="queued",
        sha256=sha256,
        mime_type=mime_type or "application/octet-stream",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    task = create_render_task(
        db,
        project_id=project_id,
        task_type="parse_document",
        params={"doc_id": doc.id},
        message="解析招标资料中…",
    )
    dispatch(db, task=task, async_func=parse_document_task, sync_func=parse_document_sync)
    return doc


@router.post("", response_model=SourceDocumentOut, status_code=201, summary="上传招标资料")
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    doc_type: str = Form("tender"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceDocument:
    _get_owned_project(db, project_id, current)

    original_name = _safe_filename(file.filename or "未命名文件")
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise ConflictError(f"不支持的文件类型 {ext}，支持: {', '.join(sorted(ALLOWED_TYPES))}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ConflictError(f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 上限")

    # 校验实际文件类型
    real_type = _detect_real_type(original_name, content)
    if real_type not in ("pdf", "docx", "txt"):
        raise ConflictError(f"文件实际类型 {real_type} 不支持")

    # SHA-256 去重
    sha256 = compute_sha256(content)
    dup = (
        db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id, SourceDocument.sha256 == sha256)
        .first()
    )
    if dup:
        raise ConflictError(f"该文件已上传过（{dup.file_name}），避免重复上传")

    key = f"projects/{project_id}/documents/{uuid.uuid4().hex}{ext}"
    storage.save(key, content)

    doc = SourceDocument(
        project_id=project_id,
        file_name=original_name,
        file_key=key,
        file_type=real_type,
        file_size=len(content),
        doc_type=doc_type if doc_type in get_all_doc_types() else "other",
        parse_status="queued",
        sha256=sha256,
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 自动触发解析（异步）
    task = create_render_task(
        db,
        project_id=project_id,
        task_type="parse_document",
        params={"doc_id": doc.id},
        message="解析招标资料中…",
    )
    dispatch(db, task=task, async_func=parse_document_task, sync_func=parse_document_sync)

    return doc


@router.post("/uploads", response_model=ResumableUploadOut, status_code=201, summary="创建大文件分片上传")
def create_resumable_upload(
    project_id: str,
    payload: ResumableUploadInitRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ResumableUploadOut:
    """为超过普通上传上限的资料创建可断点续传会话。"""
    _get_owned_project(db, project_id, current)
    original_name = _safe_filename(payload.file_name)
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise ConflictError(f"不支持的文件类型 {ext}，支持: {', '.join(sorted(ALLOWED_TYPES))}")
    if payload.file_size > settings.resumable_upload_max_file_size:
        max_mb = settings.resumable_upload_max_file_size // 1024 // 1024
        raise ConflictError(f"文件超过 {max_mb}MB 分片上传上限")

    chunk_size = settings.resumable_upload_chunk_size
    total_chunks = (payload.file_size + chunk_size - 1) // chunk_size
    upload_id = str(uuid.uuid4())
    temp_dir = settings.resumable_upload_root / upload_id
    temp_dir.mkdir(parents=True, exist_ok=False)
    session = DocumentUploadSession(
        id=upload_id,
        project_id=project_id,
        user_id=current.id,
        file_name=original_name,
        doc_type=payload.doc_type if payload.doc_type in get_all_doc_types() else "other",
        file_size=payload.file_size,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        uploaded_chunks=[],
        status="uploading",
        temp_dir=str(temp_dir),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _upload_out(session)


@router.get("/uploads/{upload_id}", response_model=ResumableUploadOut, summary="查询分片上传进度")
def get_resumable_upload(
    project_id: str,
    upload_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ResumableUploadOut:
    _get_owned_project(db, project_id, current)
    return _upload_out(_get_owned_upload(db, project_id, upload_id, current))


@router.put("/uploads/{upload_id}/chunks/{chunk_index}", response_model=ResumableUploadOut, summary="上传一个文件分片")
async def upload_resumable_chunk(
    project_id: str,
    upload_id: str,
    chunk_index: int,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ResumableUploadOut:
    _get_owned_project(db, project_id, current)
    session = _get_owned_upload(db, project_id, upload_id, current)
    if session.status != "uploading":
        raise ConflictError("该上传任务不能继续接收分片")
    if chunk_index < 0 or chunk_index >= session.total_chunks:
        raise ConflictError("分片序号超出范围")

    expected_size = min(
        session.chunk_size,
        session.file_size - chunk_index * session.chunk_size,
    )
    target = _chunk_path(session, chunk_index)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    received = 0
    try:
        with target.open("wb") as output:
            async for block in request.stream():
                received += len(block)
                if received > expected_size:
                    raise ConflictError("分片大小超出预期")
                digest.update(block)
                output.write(block)
        if received != expected_size:
            raise ConflictError(f"分片大小不完整，期望 {expected_size} 字节，实际 {received} 字节")
        expected_sha = request.headers.get("X-Chunk-SHA256")
        if expected_sha and expected_sha.lower() != digest.hexdigest():
            raise ConflictError("分片校验失败，请重试该分片")
    except Exception:
        target.unlink(missing_ok=True)
        raise

    uploaded = set(int(index) for index in (session.uploaded_chunks or []))
    uploaded.add(chunk_index)
    session.uploaded_chunks = sorted(uploaded)
    db.commit()
    db.refresh(session)
    return _upload_out(session)


@router.post("/uploads/{upload_id}/complete", response_model=SourceDocumentOut, summary="合并分片并提交解析")
def complete_resumable_upload(
    project_id: str,
    upload_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceDocument:
    _get_owned_project(db, project_id, current)
    session = _get_owned_upload(db, project_id, upload_id, current)
    if session.status == "completed" and session.document_id:
        doc = db.get(SourceDocument, session.document_id)
        if doc:
            return doc
    if session.status != "uploading":
        raise ConflictError("该上传任务不能完成")
    uploaded = set(int(index) for index in (session.uploaded_chunks or []))
    expected = set(range(session.total_chunks))
    if uploaded != expected:
        raise ConflictError(f"仍缺少 {len(expected - uploaded)} 个分片，请继续上传")

    directory = Path(session.temp_dir)
    assembled = directory / "assembled.bin"
    digest = hashlib.sha256()
    total = 0
    try:
        with assembled.open("wb") as destination:
            for chunk_index in range(session.total_chunks):
                part = _chunk_path(session, chunk_index)
                if not part.exists():
                    raise ConflictError(f"分片 {chunk_index + 1} 不存在，请重新上传")
                with part.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        total += len(block)
                        digest.update(block)
                        destination.write(block)
        if total != session.file_size:
            raise ConflictError("合并后的文件大小校验失败")

        with assembled.open("rb") as source:
            real_type = _detect_real_type(session.file_name, source.read(64 * 1024))
        if real_type not in ("pdf", "docx", "txt"):
            raise ConflictError(f"文件实际类型 {real_type} 不支持")

        ext = Path(session.file_name).suffix.lower()
        key = f"projects/{project_id}/documents/{uuid.uuid4().hex}{ext}"
        storage.save_file(key, assembled)
        try:
            doc = _create_document(
                db,
                project_id=project_id,
                original_name=session.file_name,
                real_type=real_type,
                doc_type=session.doc_type,
                size=total,
                sha256=digest.hexdigest(),
                mime_type="application/octet-stream",
                file_key=key,
            )
        except Exception:
            storage.delete(key)
            raise
        session.status = "completed"
        session.sha256 = digest.hexdigest()
        session.document_id = doc.id
        db.commit()
        return doc
    except Exception as exc:
        session.status = "failed"
        session.error_message = str(exc)[:1000]
        db.commit()
        raise
    finally:
        if session.status == "completed":
            shutil.rmtree(directory, ignore_errors=True)


@router.delete("/uploads/{upload_id}", status_code=204, summary="取消并清理分片上传")
def cancel_resumable_upload(
    project_id: str,
    upload_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    session = _get_owned_upload(db, project_id, upload_id, current)
    if session.status == "completed":
        raise ConflictError("已完成的上传不能取消")
    shutil.rmtree(Path(session.temp_dir), ignore_errors=True)
    db.delete(session)
    db.commit()


@router.get("", response_model=list[SourceDocumentOut], summary="资料列表")
def list_documents(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[SourceDocument]:
    _get_owned_project(db, project_id, current)
    return (
        db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id)
        .order_by(SourceDocument.created_at.desc())
        .all()
    )


@router.get("/types", response_model=dict, summary="文档分类枚举")
def document_types() -> dict:
    return get_all_doc_types()


@router.get("/search", response_model=list[SearchResult], summary="全文搜索")
def search_documents(
    project_id: str,
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[SearchResult]:
    _get_owned_project(db, project_id, current)
    from app.models.document_chunk import DocumentChunk

    if not q.strip():
        return []
    docs = {
        d.id: d
        for d in db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id)
        .all()
    }
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id.in_(docs.keys()), DocumentChunk.content.contains(q.strip()))
        .limit(50)
        .all()
    )
    results = []
    for c in chunks:
        doc = docs[c.document_id]
        content = c.content or ""
        idx = content.find(q.strip())
        start = max(0, idx - 40)
        highlight = content[start : start + 120] if idx >= 0 else content[:120]
        results.append(
            SearchResult(
                chunk_id=c.id,
                document_id=doc.id,
                document_name=doc.file_name,
                page=c.page_start,
                location_label=f"P{c.page_start}" if c.page_start else None,
                heading_path=c.heading_path,
                content=content,
                highlight=highlight,
            )
        )
    return results


@router.get("/{doc_id}", response_model=SourceDocumentOut, summary="资料详情")
def get_document(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceDocument:
    _get_owned_project(db, project_id, current)
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")
    return doc


@router.get("/{doc_id}/toc", response_model=list, summary="文档目录")
def get_document_toc(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")
    from app.models.document_chunk import DocumentChunk

    headings = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == doc_id,
            DocumentChunk.chunk_type == "heading",
        )
        .order_by(DocumentChunk.page_start.asc())
        .all()
    )
    return [
        {
            "heading_path": c.heading_path,
            "heading_text": (c.content or "").strip(),
            "level": len((c.heading_path or "").split(" > ")),
            "page": c.page_start,
            "page_start": c.page_start,
            "page_end": c.page_end,
        }
        for c in headings
    ]


@router.post("/{doc_id}/parse", response_model=SourceDocumentOut, summary="重新解析")
def reparse_document(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceDocument:
    _get_owned_project(db, project_id, current)
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")
    doc.parse_status = "queued"
    db.commit()
    task = create_render_task(
        db,
        project_id=project_id,
        task_type="parse_document",
        params={"doc_id": doc.id},
        message="重新解析中…",
    )
    dispatch(db, task=task, async_func=parse_document_task, sync_func=parse_document_sync)
    db.refresh(doc)
    return doc


@router.put("/{doc_id}/params", response_model=SourceDocumentOut, summary="人工确认关键参数")
def update_params(
    project_id: str,
    doc_id: str,
    payload: ParseParamsRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceDocument:
    _get_owned_project(db, project_id, current)
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")
    doc.extracted_params = payload.params
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/{doc_id}", response_model=SourceDocumentOut, summary="更新资料信息")
def update_document(
    project_id: str,
    doc_id: str,
    payload: SourceDocumentUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> SourceDocument:
    _get_owned_project(db, project_id, current)
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(doc, field, value)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=204, summary="删除资料")
def delete_document(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current)
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")

    # 删除前检查是否被分镜引用
    from app.models.extracted_fact import ExtractedFact

    referenced_shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .all()
    )
    for shot in referenced_shots:
        refs = shot.source_references or []
        if any(r.get("documentId") == doc_id for r in refs):
            raise ConflictError("该文档已被分镜引用，请先移除相关分镜的引用后再删除")

    # 同时清理该文档的 facts
    db.query(ExtractedFact).filter(ExtractedFact.document_id == doc_id).delete()

    try:
        storage.delete(doc.file_key)
    except Exception:
        pass
    db.delete(doc)
    db.commit()
