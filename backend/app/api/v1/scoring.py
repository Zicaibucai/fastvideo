"""评分点路由：列表、覆盖率。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.models.scoring_point import ScoringPoint
from app.models.user import User
from app.schemas.document import ScoringCoverage, ScoringPointOut

router = APIRouter(prefix="/projects/{project_id}/scoring", tags=["评分点"])


def _get_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


@router.get("", response_model=list[ScoringPointOut], summary="评分点列表")
def list_scoring_points(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ScoringPoint]:
    _get_project(db, project_id, current)
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
    _get_project(db, project_id, current)
    from app.services.scoring_service import compute_scoring_coverage

    result = compute_scoring_coverage(db, project_id)
    return ScoringCoverage(
        total=result["total"],
        covered=result["covered"],
        coverage_rate=result["coverage_rate"],
        points=[ScoringPointOut.model_validate(p) for p in result["points"]],
    )
