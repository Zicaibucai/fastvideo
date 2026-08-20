"""分镜/解说词路由：AI 生成、人工编辑、历史版本、重排序。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.schemas.storyboard_shot import (
    NarrationGenerateRequest,
    ShotRegenerateRequest,
    ShotReorderRequest,
    StoryboardShotCreate,
    StoryboardShotOut,
    StoryboardShotUpdate,
)
from app.services.task_runner import create_render_task, dispatch
from app.tasks.narration import gen_narration_sync, gen_narration_task

router = APIRouter(prefix="/projects/{project_id}/storyboard", tags=["分镜与解说词"])


def _get_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


@router.get("/summary", response_model=dict, summary="分镜汇总（总时长/字数/评分覆盖）")
def storyboard_summary(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    from app.services.scoring_service import compute_scoring_coverage

    coverage = compute_scoring_coverage(db, project_id)
    total_duration = sum(float(s.duration_seconds or 0) for s in shots)
    total_chars = sum(len(s.narration or "") for s in shots)
    fact_statuses = [s.fact_check_status for s in shots if s.fact_check_status]
    return {
        "shot_count": len(shots),
        "total_duration_seconds": round(total_duration, 1),
        "total_narration_characters": total_chars,
        "scoring_coverage_rate": coverage["coverage_rate"],
        "scoring_covered": coverage["covered"],
        "scoring_total": coverage["total"],
        "unverified_shot_count": sum(1 for s in fact_statuses if s in ("unverified", "conflict")),
        "fact_status_counts": {
            st: fact_statuses.count(st) for st in set(fact_statuses)
        },
    }


@router.get("", response_model=list[StoryboardShotOut], summary="分镜列表")
def list_shots(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[StoryboardShot]:
    _get_project(db, project_id, current)
    return (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )


@router.post("", response_model=StoryboardShotOut, status_code=201, summary="手动新增分镜")
def create_shot(
    project_id: str,
    payload: StoryboardShotCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> StoryboardShot:
    _get_project(db, project_id, current)
    shot = StoryboardShot(**payload.model_dump())
    db.add(shot)
    db.commit()
    db.refresh(shot)
    return shot


@router.post("/generate", response_model=dict, status_code=202, summary="AI 智能拆解生成解说词")
def generate_narration(
    project_id: str,
    payload: NarrationGenerateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    task = create_render_task(
        db,
        project_id=project_id,
        task_type="gen_narration",
        params={
            "project_id": project_id,
            "section_count": payload.section_count,
            "tone": payload.tone,
            "target_duration_seconds": payload.target_duration_seconds,
            "video_purpose": payload.video_purpose or "投标答辩",
            "aspect_ratio": payload.aspect_ratio,
            "focus_scoring_points": payload.focus_scoring_points,
            "include_company_intro": payload.include_company_intro,
            "include_construction_simulation": payload.include_construction_simulation,
            "chars_per_minute": payload.chars_per_minute,
        },
        message="AI 智能拆解解说词中…",
    )
    dispatch(db, task=task, async_func=gen_narration_task, sync_func=gen_narration_sync)
    return {"task_id": task.id, "status": task.status}


@router.get("/{shot_id}", response_model=StoryboardShotOut, summary="分镜详情")
def get_shot(
    project_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> StoryboardShot:
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")
    return shot


@router.patch("/{shot_id}", response_model=StoryboardShotOut, summary="编辑分镜（保存历史版本）")
def update_shot(
    project_id: str,
    shot_id: str,
    payload: StoryboardShotUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> StoryboardShot:
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")

    data = payload.model_dump(exclude_unset=True)

    # 记录历史版本（每次编辑前）
    if "narration" in data and data["narration"] != shot.narration:
        # 创建新列表对象，确保 SQLAlchemy 检测到 JSON 列变更
        versions = list(shot.versions or [])
        revision = max([v.get("revision", 0) for v in versions] + [0]) + 1
        versions.append(
            {
                "revision": revision,
                "narration": data["narration"],
                "visual_prompt": data.get("visual_prompt", shot.visual_prompt),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": "manual",
            }
        )
        shot.versions = versions
        shot.status = "edited"

    old_narration = shot.narration
    for field, value in data.items():
        setattr(shot, field, value)

    # Phase 4：解说词修改后标记旧配音与字幕为 stale（不删除历史版本）
    if "narration" in data and data["narration"] != old_narration:
        from app.services.voice_service import mark_shot_narration_changed

        mark_shot_narration_changed(db, shot, old_narration, data["narration"])

    db.commit()
    db.refresh(shot)
    return shot


@router.post("/{shot_id}/restore", response_model=StoryboardShotOut, summary="恢复历史版本")
def restore_shot_version(
    project_id: str,
    shot_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> StoryboardShot:
    """payload: {"revision": 2}"""
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")
    revision = payload.get("revision")
    versions = shot.versions or []
    target = next((v for v in versions if v.get("revision") == revision), None)
    if not target:
        raise NotFoundError("版本不存在")
    prev_narration = shot.narration
    shot.narration = target.get("narration", shot.narration)
    shot.visual_prompt = target.get("visual_prompt", shot.visual_prompt)
    if target.get("visual_type"):
        shot.visual_type = target.get("visual_type")
    shot.status = "edited"
    # Phase 4：恢复解说词后同样标记旧配音为 stale
    from app.services.voice_service import mark_shot_narration_changed

    mark_shot_narration_changed(db, shot, prev_narration, shot.narration)
    db.commit()
    db.refresh(shot)
    return shot


@router.post("/reorder", response_model=list[StoryboardShotOut], summary="分镜排序")
def reorder_shots(
    project_id: str,
    payload: ShotReorderRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[StoryboardShot]:
    _get_project(db, project_id, current)
    shots = {
        shot.id: shot
        for shot in db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .all()
    }
    for index, shot_id in enumerate(payload.shot_ids, start=1):
        if shot_id in shots:
            shots[shot_id].sequence = index
    db.commit()
    return (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )


@router.post("/{shot_id}/regenerate", status_code=202, summary="AI 重新生成单个分镜")
def regenerate_shot(
    project_id: str,
    shot_id: str,
    payload: ShotRegenerateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")

    task = create_render_task(
        db,
        project_id=project_id,
        shot_id=shot_id,
        task_type="gen_narration",
        params={
            "project_id": project_id,
            "shot_id": shot_id,
            "regenerate_shot_id": shot_id,
            "prompt_hint": payload.prompt_hint,
        },
        message="重新生成解说词中…",
    )
    dispatch(db, task=task, async_func=gen_narration_task, sync_func=gen_narration_sync)
    db.refresh(task)
    return {"task_id": task.id, "status": task.status, "shot_id": shot_id}


@router.delete("/{shot_id}", status_code=204, summary="删除分镜")
def delete_shot(
    project_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")
    db.delete(shot)
    db.commit()


# ============================================================
# 分镜画面绑定（Phase 3）
# ============================================================

@router.post("/{shot_id}/visual/select", response_model=dict, summary="选择渲染版本作为分镜画面")
def select_shot_visual(
    project_id: str,
    shot_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    """payload: {"version_id": "..."}"""
    _get_project(db, project_id, current)
    version_id = payload.get("version_id")
    if not version_id:
        raise NotFoundError("缺少 version_id")
    from app.services.render_service import select_version_for_shot

    try:
        result = select_version_for_shot(db, project_id, shot_id, version_id, current.username)
    except RuntimeError as exc:
        from app.core.exceptions import ConflictError

        raise ConflictError(str(exc))
    return result


@router.get("/{shot_id}/visual/history", response_model=dict, summary="分镜画面选择历史")
def shot_visual_history(
    project_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")
    return {
        "shot_id": shot_id,
        "current_image_asset_id": shot.image_asset_id,
        "current_render_version_id": shot.render_version_id,
        "source_model_asset_id": shot.source_model_asset_id,
        "visual_review_status": shot.visual_review_status,
        "history": shot.visual_history or [],
    }


@router.post("/{shot_id}/visual/restore", response_model=dict, summary="恢复历史画面选择")
def restore_shot_visual(
    project_id: str,
    shot_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    """payload: {"version_id": "..."}"""
    _get_project(db, project_id, current)
    version_id = payload.get("version_id")
    if not version_id:
        raise NotFoundError("缺少 version_id")
    from app.services.render_service import restore_shot_visual as restore_visual

    try:
        return restore_visual(db, project_id, shot_id, version_id, current.username)
    except RuntimeError as exc:
        from app.core.exceptions import ConflictError

        raise ConflictError(str(exc))
