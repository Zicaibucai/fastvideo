"""评分点路由：列表、覆盖率。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.permissions import (
    get_project_access,
    PERM_DOCUMENT_EDIT,
    PERM_DOCUMENT_UPLOAD,
    PERM_DOCUMENT_VIEW,
    PERM_EXPORT_DEMO,
    PERM_EXPORT_FORMAL,
    PERM_EXPORT_VIEW,
    PERM_FACT_EDIT,
    PERM_FACT_VIEW,
    PERM_MEDIA_EDIT,
    PERM_MEDIA_VIEW,
    PERM_PROJECT_VIEW,
    PERM_SCORING_VIEW,
    PERM_STORYBOARD_EDIT,
    PERM_STORYBOARD_VIEW,
    PERM_VIDEO_EDIT,
    PERM_VIDEO_VIEW,
    PERM_VOICE_EDIT,
    PERM_VOICE_VIEW,
)
from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.models.scoring_point import ScoringPoint
from app.models.user import User
from app.schemas.document import ScoringCoverage, ScoringPointOut

router = APIRouter(prefix="/projects/{project_id}/scoring", tags=["评分点"])


def _get_project(db: Session, project_id: str, user: User, permission: str = PERM_SCORING_VIEW) -> Project:
    """统一项目访问：成员校验 + 细粒度权限（非成员 404，权限不足 403）。"""
    return get_project_access(db, project_id, user, permission).project


@router.get("", response_model=list[ScoringPointOut], summary="评分点列表")
def list_scoring_points(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ScoringPoint]:
    _get_project(db, project_id, current, PERM_SCORING_VIEW)
    return (
        db.query(ScoringPoint)
        .filter(ScoringPoint.project_id == project_id)
        .order_by(ScoringPoint.created_at.asc())
        .all()
    )


@router.get("/coverage", response_model=ScoringCoverage, summary="评分点覆盖率")
def scoring_coverage(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ScoringCoverage:
    _get_project(db, project_id, current, PERM_SCORING_VIEW)
    from app.services.scoring_service import compute_scoring_coverage

    result = compute_scoring_coverage(db, project_id)
    return ScoringCoverage(
        total=result["total"],
        covered=result["covered"],
        coverage_rate=result["coverage_rate"],
        points=[ScoringPointOut.model_validate(p) for p in result["points"]],
    )
