"""文档阅读器路由：按页获取内容、表格、OCR 标记、引用该页的分镜。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.document_page import DocumentPage
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.schemas.document import DocumentPageContent, DocumentPageOut

router = APIRouter(prefix="/projects/{project_id}/reader", tags=["文档阅读器"])


def _get_owned_doc(db: Session, project_id: str, doc_id: str, user: User) -> SourceDocument:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    doc = db.get(SourceDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise NotFoundError("资料不存在")
    return doc


@router.get("/{doc_id}/pages", response_model=list[DocumentPageOut], summary="文档页面列表")
def list_pages(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[DocumentPage]:
    _get_owned_doc(db, project_id, doc_id, current)
    return (
        db.query(DocumentPage)
        .filter(DocumentPage.document_id == doc_id)
        .order_by(DocumentPage.page_number.asc())
        .all()
    )


@router.get("/{doc_id}/pages/{page_number}", response_model=DocumentPageContent, summary="按页获取内容")
def get_page_content(
    project_id: str,
    doc_id: str,
    page_number: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> DocumentPage:
    _get_owned_doc(db, project_id, doc_id, current)
    page = (
        db.query(DocumentPage)
        .filter(
            DocumentPage.document_id == doc_id,
            DocumentPage.page_number == page_number,
        )
        .first()
    )
    if not page:
        raise NotFoundError("页面不存在")
    return page


@router.get("/{doc_id}/page-summary", response_model=dict, summary="页面统计（OCR/失败/表格）")
def page_summary(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    doc = _get_owned_doc(db, project_id, doc_id, current)
    pages = (
        db.query(DocumentPage)
        .filter(DocumentPage.document_id == doc_id)
        .all()
    )
    return {
        "total": len(pages),
        "text_pages": sum(1 for p in pages if p.page_type == "text"),
        "scan_pages": sum(1 for p in pages if p.page_type == "scan"),
        "table_pages": sum(1 for p in pages if p.page_type in ("table", "mixed")),
        "ocr_success": sum(1 for p in pages if p.ocr_status == "success"),
        "ocr_failed": sum(1 for p in pages if p.ocr_status == "failed"),
        "ocr_pending": sum(1 for p in pages if p.ocr_status in ("pending", "none") and p.page_type == "scan"),
    }


@router.get("/{doc_id}/referencing-shots", response_model=list, summary="引用该文档的分镜")
def referencing_shots(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_owned_doc(db, project_id, doc_id, current)
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    result = []
    for shot in shots:
        refs = shot.source_references or []
        if any(r.get("documentId") == doc_id for r in refs):
            result.append(
                {
                    "id": shot.id,
                    "sequence": shot.sequence,
                    "title": shot.title,
                    "narration": (shot.narration or "")[:100],
                    "page": next(
                        (r.get("page") for r in refs if r.get("documentId") == doc_id),
                        None,
                    ),
                }
            )
    return result
