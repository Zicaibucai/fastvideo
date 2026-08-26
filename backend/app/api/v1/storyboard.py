"""分镜/解说词路由：AI 生成、人工编辑、历史版本、重排序。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.asset import Asset
from app.models.base import utc_now_iso
from app.models.audio_version import AudioVersion
from app.models.project import Project
from app.models.render_job import RenderJob
from app.models.render_task import RenderTask
from app.models.render_version import RenderVersion
from app.models.narration_beat import NarrationBeat
from app.models.narration_run import NarrationEvidence, NarrationEvidenceBatch, NarrationRun
from app.models.storyboard_shot import StoryboardShot
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.models.user import User
from app.schemas.storyboard_shot import (
    NarrationDocumentUpdate,
    NarrationGenerateRequest,
    ShotRegenerateRequest,
    ShotReorderRequest,
    StoryboardResegmentRequest,
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


def _select_visual_version(
    db: Session,
    *,
    project_id: str,
    shot: StoryboardShot,
    version: RenderVersion,
    username: str,
) -> dict:
    """将模型截图渲染版本绑定到分镜，并标记关联视频分段需要重建。

    这是画面制作的绑定，不适用于 AI 视频结果；AI 视频只在 VideoSegment.visual_asset_id
    中由视频工程显式选择。
    """
    if version.is_deleted or not version.result_asset_id:
        raise NotFoundError("渲染版本不存在")
    result_asset = db.get(Asset, version.result_asset_id)
    if not result_asset or result_asset.project_id != project_id or result_asset.asset_type != "image":
        raise NotFoundError("渲染版本不属于当前项目")
    if version.source_asset_id:
        source_asset = db.get(Asset, version.source_asset_id)
        if not source_asset or source_asset.project_id != project_id:
            raise NotFoundError("渲染源图不属于当前项目")
    if version.render_job_id:
        job = db.get(RenderJob, version.render_job_id)
        if not job or job.project_id != project_id:
            raise NotFoundError("渲染版本不属于当前项目")

    previous = shot.render_version_id
    if previous and previous != version.id:
        history = list(shot.visual_history or [])
        history.append({
            "render_version_id": previous,
            "image_asset_id": shot.image_asset_id,
            "selected_at": utc_now_iso(),
            "selected_by": username,
        })
        shot.visual_history = history[-50:]

    shot.source_model_asset_id = version.source_asset_id
    shot.render_version_id = version.id
    shot.image_asset_id = version.result_asset_id
    shot.visual_review_status = "approved"

    # 选择状态按渲染源图互斥，便于素材库恢复当前版本。
    if version.source_asset_id:
        db.query(RenderVersion).filter(
            RenderVersion.source_asset_id == version.source_asset_id,
            RenderVersion.is_deleted.is_(False),
        ).update({"is_selected": False}, synchronize_session=False)
    version.is_selected = True
    version.selected_by = username
    version.selected_at = utc_now_iso()

    affected = []
    segments = (
        db.query(VideoSegment)
        .join(VideoProject, VideoProject.id == VideoSegment.video_project_id)
        .filter(VideoProject.project_id == project_id, VideoSegment.storyboard_shot_id == shot.id)
        .all()
    )
    for segment in segments:
        segment.needs_rebuild = True
        segment.output_key = None
        segment.render_progress = 0
        segment.rendered_at = None
        if segment.render_status == "success":
            segment.render_status = "pending"
        affected.append(segment.video_project_id)

    db.commit()
    db.refresh(shot)
    return {
        "render_version_id": version.id,
        "image_asset_id": version.result_asset_id,
        "visual_review_status": shot.visual_review_status,
        "affected_videos": affected,
    }


@router.get("/summary", response_model=dict, summary="分镜汇总（总时长/字数/评分覆盖）")
def storyboard_summary(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    from app.services.scoring_service import compute_scoring_coverage

    coverage = compute_scoring_coverage(db, project_id)
    total_duration = sum(float(s.duration_seconds or 0) for s in shots)
    total_chars = sum(len(s.narration or "") for s in shots)
    beat_count = db.query(NarrationBeat).filter(NarrationBeat.project_id == project_id).count()
    fact_statuses = [s.fact_check_status for s in shots if s.fact_check_status]
    return {
        "shot_count": len(shots),
        "beat_count": beat_count,
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
) -> list[dict]:
    _get_project(db, project_id, current)
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    selected_audio = {
        row.storyboard_shot_id: row
        for row in db.query(AudioVersion)
        .filter(
            AudioVersion.project_id == project_id,
            AudioVersion.is_selected.is_(True),
            AudioVersion.is_deleted.is_(False),
        )
        .all()
    }
    return [
        {
            **shot.to_dict(),
            "audio_duration_status": getattr(selected_audio.get(shot.id), "duration_status", None),
            "audio_quality_status": getattr(selected_audio.get(shot.id), "quality_status", None),
            "audio_is_stale": bool(getattr(selected_audio.get(shot.id), "is_stale", False)),
        }
        for shot in shots
    ]


@router.post("/{shot_id}/visual/select", response_model=dict, summary="选择分镜渲染画面")
def select_visual_version(
    project_id: str,
    shot_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id or not shot.is_active:
        raise NotFoundError("分镜不存在")
    version_id = payload.get("version_id")
    version = db.get(RenderVersion, version_id) if version_id else None
    if not version:
        raise NotFoundError("渲染版本不存在")
    return _select_visual_version(
        db,
        project_id=project_id,
        shot=shot,
        version=version,
        username=current.username,
    )


@router.post("/{shot_id}/visual/restore", response_model=dict, summary="恢复分镜历史渲染画面")
def restore_visual_version(
    project_id: str,
    shot_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id or not shot.is_active:
        raise NotFoundError("分镜不存在")
    version_id = payload.get("version_id")
    version = db.get(RenderVersion, version_id) if version_id else None
    if not version:
        raise NotFoundError("渲染版本不存在")
    result = _select_visual_version(
        db,
        project_id=project_id,
        shot=shot,
        version=version,
        username=current.username,
    )
    result["restored"] = True
    return result


@router.post("", response_model=StoryboardShotOut, status_code=201, summary="手动新增分镜")
def create_shot(
    project_id: str,
    payload: StoryboardShotCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> StoryboardShot:
    _get_project(db, project_id, current)
    data = payload.model_dump()
    insert_at = data.pop("insert_at", None)
    if insert_at is not None:
        existing = (
            db.query(StoryboardShot)
            .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
            .order_by(StoryboardShot.sequence.desc())
            .all()
        )
        for existing_shot in existing:
            if existing_shot.sequence >= insert_at:
                existing_shot.sequence += 1
        data["sequence"] = insert_at
    shot = StoryboardShot(**data)
    db.add(shot)
    from app.services.narration_engine import rebuild_project_narration_beats

    db.flush()
    rebuild_project_narration_beats(db, project_id)
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
            "target_shot_count": payload.target_shot_count,
            "tone": payload.tone,
            "target_duration_seconds": payload.target_duration_seconds,
            "video_purpose": payload.video_purpose or "投标答辩",
            "aspect_ratio": payload.aspect_ratio,
            "focus_scoring_points": payload.focus_scoring_points,
            "include_company_intro": payload.include_company_intro,
            "include_construction_simulation": payload.include_construction_simulation,
            "chars_per_minute": payload.chars_per_minute,
            "generation_mode": payload.generation_mode,
            "custom_requirements": payload.custom_requirements,
            "predefined_outline": payload.predefined_outline,
            "target_beat_count": payload.target_beat_count,
            "evidence_batch_chars": payload.evidence_batch_chars,
            "evidence_concurrency": payload.evidence_concurrency,
            "evidence_auto_approve": payload.evidence_auto_approve,
            "evidence_run_id": payload.evidence_run_id,
            "strict_fact_mode": payload.strict_fact_mode,
        },
        message="AI 智能拆解解说词中…",
    )
    task.params = {**(task.params or {}), "task_id": task.id}
    db.commit()
    dispatch(db, task=task, async_func=gen_narration_task, sync_func=gen_narration_sync)
    return {"task_id": task.id, "status": task.status}


@router.get("/evidence/runs/{run_id}", response_model=dict, summary="查看长文证据运行")
def narration_evidence_run(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    run = db.get(NarrationRun, run_id)
    if not run or run.project_id != project_id:
        raise NotFoundError("证据运行不存在")
    batches = (
        db.query(NarrationEvidenceBatch)
        .filter(NarrationEvidenceBatch.run_id == run_id)
        .order_by(NarrationEvidenceBatch.batch_index.asc())
        .all()
    )
    evidence = (
        db.query(NarrationEvidence)
        .filter(NarrationEvidence.run_id == run_id)
        .order_by(NarrationEvidence.topic.asc(), NarrationEvidence.created_at.asc())
        .all()
    )
    return {
        "run": run.to_dict(),
        "batches": [batch.to_dict() for batch in batches],
        "evidence": [row.to_dict() for row in evidence],
        "approved_count": sum(1 for row in evidence if row.review_status == "approved"),
    }


@router.post("/evidence/runs/{run_id}/approve", response_model=dict, summary="审核通过长文证据")
def approve_narration_evidence(
    project_id: str,
    run_id: str,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    run = db.get(NarrationRun, run_id)
    if not run or run.project_id != project_id:
        raise NotFoundError("证据运行不存在")
    from app.services.narration_evidence import approve_evidence

    ids = (payload or {}).get("evidence_ids")
    count = approve_evidence(db, run_id, ids if isinstance(ids, list) else None)
    result: dict = {"run_id": run_id, "approved_count": count, "status": run.status}
    if (payload or {}).get("continue_generation"):
        params = dict(run.params or {})
        params.update({"project_id": project_id, "evidence_run_id": run_id, "evidence_auto_approve": True})
        task = create_render_task(
            db,
            project_id=project_id,
            task_type="gen_narration",
            params=params,
            message="已通过证据审核，继续生成解说词…",
        )
        dispatch(db, task=task, async_func=gen_narration_task, sync_func=gen_narration_sync)
        result["task_id"] = task.id
    return result


@router.patch("/document", response_model=dict, summary="保存连续文稿并重建字幕节拍")
def update_narration_document(
    project_id: str,
    payload: NarrationDocumentUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shots = {
        shot.id: shot
        for shot in db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .all()
    }
    if any(item.shot_id not in shots for item in payload.shots):
        raise NotFoundError("文稿中包含不存在的分镜")

    updated_count = 0
    for item in payload.shots:
        shot = shots[item.shot_id]
        if item.narration == (shot.narration or ""):
            continue
        versions = list(shot.versions or [])
        revision = max([v.get("revision", 0) for v in versions] + [0]) + 1
        versions.append(
            {
                "revision": revision,
                "narration": item.narration,
                "visual_prompt": shot.visual_prompt,
                "visual_type": shot.visual_type,
                "created_at": utc_now_iso(),
                "source": "manual",
            }
        )
        old_narration = shot.narration or ""
        shot.narration = item.narration
        shot.versions = versions
        shot.status = "edited"
        from app.services.voice_service import mark_shot_narration_changed

        mark_shot_narration_changed(db, shot, old_narration, item.narration)
        updated_count += 1

    db.flush()
    from app.services.narration_engine import rebuild_project_narration_beats

    beat_count = rebuild_project_narration_beats(db, project_id)
    db.commit()
    return {"updated_count": updated_count, "beat_count": beat_count}


@router.get("/beats", response_model=list[dict], summary="旁白短句时间轴")
def list_narration_beats(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[dict]:
    _get_project(db, project_id, current)
    return [
        beat.to_dict()
        for beat in db.query(NarrationBeat)
        .filter(NarrationBeat.project_id == project_id)
        .order_by(NarrationBeat.sequence.asc())
        .all()
    ]


@router.post("/resegment", response_model=dict, status_code=202, summary="AI 根据正文重新分镜")
def resegment_narration(
    project_id: str,
    payload: StoryboardResegmentRequest,
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
            "resegment_storyboard": True,
            "target_shot_count": payload.target_shot_count,
            "chars_per_minute": payload.chars_per_minute,
            "instructions": payload.instructions,
        },
        message="AI 正在根据正文重新调整分镜…",
    )
    dispatch(db, task=task, async_func=gen_narration_task, sync_func=gen_narration_sync)
    db.refresh(task)
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
                "created_at": utc_now_iso(),
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

        from app.services.narration_engine import rebuild_project_narration_beats

        db.flush()
        rebuild_project_narration_beats(db, project_id)
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
    from app.services.narration_engine import rebuild_project_narration_beats

    db.flush()
    rebuild_project_narration_beats(db, project_id)
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
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .all()
    }
    for index, shot_id in enumerate(payload.shot_ids, start=1):
        if shot_id in shots:
            shots[shot_id].sequence = index
    from app.services.narration_engine import rebuild_project_narration_beats

    db.flush()
    rebuild_project_narration_beats(db, project_id)
    db.commit()
    return (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
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
    # 删除分镜只做归档，保留其稳定 ID 供视频时间线、素材和审计追踪。
    shot.is_active = False
    shot.status = "archived"
    from app.services.narration_engine import rebuild_project_narration_beats

    db.flush()
    rebuild_project_narration_beats(db, project_id)
    db.commit()
