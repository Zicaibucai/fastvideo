"""工程参数台账路由：列表、确认、驳回、修改、冲突对比。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.extracted_fact import ExtractedFact
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.models.user import User
from app.schemas.document import ExtractedFactOut, FactConfirmRequest, FactConfirmResult

router = APIRouter(prefix="/projects/{project_id}/facts", tags=["工程参数台账"])


def _get_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def _to_out(fact: ExtractedFact, doc_name: str | None = None) -> ExtractedFactOut:
    return ExtractedFactOut(
        id=fact.id,
        project_id=fact.project_id,
        document_id=fact.document_id,
        document_name=doc_name,
        page_number=fact.page_number,
        location_label=fact.location_label,
        fact_type=fact.fact_type,
        fact_name=fact.fact_name,
        fact_value=fact.fact_value,
        unit=fact.unit,
        source_quote=fact.source_quote,
        confidence=fact.confidence,
        verification_status=fact.verification_status,
        confirmed_by=fact.confirmed_by,
        confirmed_at=fact.confirmed_at,
        candidates=fact.candidates,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


@router.get("", response_model=list[ExtractedFactOut], summary="参数列表")
def list_facts(
    project_id: str,
    status: str | None = Query(None, description="unverified/confirmed/rejected/conflict"),
    fact_type: str | None = None,
    unverified_only: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ExtractedFactOut]:
    _get_project(db, project_id, current)
    query = db.query(ExtractedFact).filter(ExtractedFact.project_id == project_id)
    if status:
        query = query.filter(ExtractedFact.verification_status == status)
    if unverified_only:
        query = query.filter(ExtractedFact.verification_status.in_(["unverified", "conflict"]))
    if fact_type:
        query = query.filter(ExtractedFact.fact_type == fact_type)

    facts = query.order_by(ExtractedFact.fact_name.asc(), ExtractedFact.created_at.asc()).all()

    doc_names = {
        d.id: d.file_name
        for d in db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id)
        .all()
    }
    return [_to_out(f, doc_names.get(f.document_id)) for f in facts]


@router.get("/conflicts", response_model=list[ExtractedFactOut], summary="冲突参数")
def list_conflicts(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ExtractedFactOut]:
    _get_project(db, project_id, current)
    facts = (
        db.query(ExtractedFact)
        .filter(
            ExtractedFact.project_id == project_id,
            ExtractedFact.verification_status == "conflict",
        )
        .all()
    )
    doc_names = {
        d.id: d.file_name
        for d in db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id)
        .all()
    }
    return [_to_out(f, doc_names.get(f.document_id)) for f in facts]


@router.get("/types", response_model=dict, summary="参数类型枚举")
def fact_types() -> dict:
    from app.services.fact_extractor import FACT_TYPE_LABELS

    return FACT_TYPE_LABELS


@router.post("/{fact_id}/confirm", response_model=FactConfirmResult, summary="确认/驳回/修改参数")
def confirm_fact(
    project_id: str,
    fact_id: str,
    payload: FactConfirmRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> FactConfirmResult:
    _get_project(db, project_id, current)
    fact = db.get(ExtractedFact, fact_id)
    if not fact or fact.project_id != project_id:
        raise NotFoundError("参数不存在")

    # 若确认采用新值，则把同名的其它事实标记为 rejected（排除候选）
    if payload.status == "confirmed" and payload.fact_value:
        # 更新当前事实
        fact.fact_value = payload.fact_value
        if payload.unit:
            fact.unit = payload.unit
        fact.verification_status = "confirmed"
        fact.confirmed_by = current.username
        fact.confirmed_at = time.strftime("%Y-%m-%d %H:%M:%S")
        fact.candidates = None

        # 同一 fact_name 的其它 unverified/conflict 事实 → rejected
        others = (
            db.query(ExtractedFact)
            .filter(
                ExtractedFact.project_id == project_id,
                ExtractedFact.fact_name == fact.fact_name,
                ExtractedFact.id != fact.id,
            )
            .all()
        )
        for other in others:
            if other.verification_status != "confirmed":
                other.verification_status = "rejected"
                other.candidates = None
    else:
        fact.verification_status = payload.status
        fact.confirmed_by = current.username if payload.status == "confirmed" else None
        fact.confirmed_at = (
            time.strftime("%Y-%m-%d %H:%M:%S") if payload.status == "confirmed" else None
        )
        if payload.status == "rejected":
            fact.candidates = None

    db.commit()

    # 同步到 Project 快捷字段
    from app.services.fact_extractor import sync_project_key_params

    all_facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.project_id == project_id)
        .all()
    )
    project = _get_project(db, project_id, current)
    sync_project_key_params(db, project, all_facts)

    return FactConfirmResult(id=fact_id, status=fact.verification_status, message="已更新")
