"""项目路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
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

router = APIRouter(prefix="/projects", tags=["项目"])


def _with_stats(db: Session, project: Project, user_id: str) -> ProjectDetail:
    doc_count = db.scalar(
        select(func.count(SourceDocument.id)).where(SourceDocument.project_id == project.id)
    ) or 0
    shot_count = db.scalar(
        select(func.count(StoryboardShot.id)).where(StoryboardShot.project_id == project.id)
    ) or 0
    asset_count = db.scalar(
        select(func.count(Asset.id)).where(Asset.project_id == project.id)
    ) or 0
    base = ProjectDetail.model_validate(project)
    base.doc_count = doc_count
    base.shot_count = shot_count
    base.asset_count = asset_count
    return base


@router.get("", response_model=Page[ProjectOut], summary="项目列表")
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Page[ProjectOut]:
    stmt = select(Project).where(Project.owner_id == current.id).order_by(Project.created_at.desc())
    if status:
        stmt = stmt.where(Project.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return Page(
        items=[ProjectOut.model_validate(p) for p in items],
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
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectDetail, summary="项目详情")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project or project.owner_id != current.id:
        raise NotFoundError("项目不存在")
    return _with_stats(db, project, current.id)


@router.patch("/{project_id}", response_model=ProjectOut, summary="更新项目")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != current.id:
        raise NotFoundError("项目不存在")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204, summary="删除项目")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project or project.owner_id != current.id:
        raise NotFoundError("项目不存在")
    db.delete(project)
    db.commit()
