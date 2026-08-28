"""项目路由。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.asset import Asset
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectDetail, ProjectOut, ProjectUpdate
from app.services.revision import check_revision
from app.services.permissions import (
    accessible_project_ids,
    ensure_owner_member,
    get_project_access,
    PERM_PROJECT_DELETE,
    PERM_PROJECT_EDIT,
    PERM_PROJECT_VIEW,
    PERM_REVIEW_POLICY,
)

router = APIRouter(prefix="/projects", tags=["项目"])


def _with_stats(db: Session, project: Project, user_id: str) -> ProjectDetail:
    doc_count = db.scalar(
        select(func.count(SourceDocument.id)).where(SourceDocument.project_id == project.id)
    ) or 0
    shot_count = db.scalar(
        select(func.count(StoryboardShot.id)).where(StoryboardShot.project_id == project.id, StoryboardShot.is_active.is_(True))
    ) or 0
    asset_count = db.scalar(
        select(func.count(Asset.id)).where(Asset.project_id == project.id)
    ) or 0
    base = ProjectDetail.model_validate(project)
    base.doc_count = doc_count
    base.shot_count = shot_count
    base.asset_count = asset_count
    access = get_project_access(db, project.id, _load_user(db, user_id))
    base.my_role = access.role
    base.my_permissions = sorted(access.permissions)
    return base


def _load_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    return user


def _with_stats_bulk(db: Session, projects: list[Project]) -> list[ProjectOut]:
    """为项目列表批量补齐资料、分镜和素材数量，避免列表接口返回默认 0。"""
    if not projects:
        return []

    project_ids = [project.id for project in projects]
    doc_counts = dict(
        db.execute(
            select(SourceDocument.project_id, func.count(SourceDocument.id))
            .where(SourceDocument.project_id.in_(project_ids))
            .group_by(SourceDocument.project_id)
        ).all()
    )
    shot_counts = dict(
        db.execute(
            select(StoryboardShot.project_id, func.count(StoryboardShot.id))
            .where(StoryboardShot.project_id.in_(project_ids), StoryboardShot.is_active.is_(True))
            .group_by(StoryboardShot.project_id)
        ).all()
    )
    asset_counts = dict(
        db.execute(
            select(Asset.project_id, func.count(Asset.id))
            .where(Asset.project_id.in_(project_ids))
            .group_by(Asset.project_id)
        ).all()
    )

    result: list[ProjectOut] = []
    for project in projects:
        item = ProjectOut.model_validate(project)
        item.doc_count = doc_counts.get(project.id, 0)
        item.shot_count = shot_counts.get(project.id, 0)
        item.asset_count = asset_counts.get(project.id, 0)
        result.append(item)
    return result


@router.get("", response_model=Page[ProjectOut], summary="项目列表")
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    sort_by: Literal["last_entered_at", "created_at", "name"] = Query(
        "last_entered_at", description="排序字段"
    ),
    sort_order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Page[ProjectOut]:
    sort_column = {
        "last_entered_at": Project.last_entered_at,
        "created_at": Project.created_at,
        "name": Project.name,
    }[sort_by]
    order_clause = desc(sort_column) if sort_order == "desc" else asc(sort_column)
    order_clauses = [order_clause]
    if sort_by == "last_entered_at":
        order_clauses[0] = order_clause.nulls_last()
        order_clauses.append(
            Project.created_at.desc() if sort_order == "desc" else Project.created_at.asc()
        )
    project_ids = accessible_project_ids(db, current)
    stmt = select(Project).order_by(*order_clauses)
    if project_ids is not None:
        stmt = stmt.where(Project.id.in_(project_ids))
    if status:
        stmt = stmt.where(Project.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return Page(
        items=_with_stats_bulk(db, items),
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


@router.post("", response_model=ProjectOut, status_code=201, summary="创建项目")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Project:
    project = Project(
        owner_id=current.id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
    )
    db.add(project)
    db.flush()
    ensure_owner_member(db, project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectDetail, summary="项目详情")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ProjectDetail:
    access = get_project_access(db, project_id, current, PERM_PROJECT_VIEW)
    return _with_stats(db, access.project, current.id)


@router.post("/{project_id}/enter", response_model=ProjectOut, summary="记录进入项目")
def enter_project(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Project:
    """Record an intentional project visit without making GET stateful."""
    access = get_project_access(db, project_id, current, PERM_PROJECT_VIEW)
    project = access.project
    project.last_entered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut, summary="更新项目")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Project:
    access = get_project_access(db, project_id, current, PERM_PROJECT_EDIT)
    project = access.project
    data = payload.model_dump(exclude_unset=True)
    check_revision(project, data.pop("base_revision", None))
    # review_policy 变更需要专门权限
    if "review_policy" in data:
        access.require(PERM_REVIEW_POLICY)
    for field, value in data.items():
        setattr(project, field, value)
    project.revision = (project.revision or 1) + 1
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204, summary="删除项目")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    access = get_project_access(db, project_id, current, PERM_PROJECT_DELETE)
    project = access.project
    from app.services.audit import log_action

    log_action(
        db,
        user=current,
        project_id=project.id,
        action="project_delete",
        entity_type="project",
        entity_id=project.id,
        detail={"name": project.name},
        commit=False,
    )
    db.delete(project)
    db.commit()
