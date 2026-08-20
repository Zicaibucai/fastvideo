"""素材库路由：上传、列表、删除 + AI 生成（图片/视频/TTS）。"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.storage import storage
from app.models.asset import Asset
from app.models.project import Project
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.schemas.asset import AssetCreate, AssetOut, AssetUpdate
from app.schemas.common import Message
from app.services.task_runner import create_render_task, dispatch
from app.tasks.assets import gen_image_sync, gen_image_task, gen_tts_sync, gen_tts_task, gen_video_sync, gen_video_task

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["素材库"])


def _get_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def _get_shot(db: Session, project_id: str, shot_id: str) -> StoryboardShot:
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id:
        raise NotFoundError("分镜不存在")
    return shot


@router.get("", response_model=list[AssetOut], summary="素材列表")
def list_assets(
    project_id: str,
    asset_type: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[Asset]:
    _get_project(db, project_id, current)
    query = db.query(Asset).filter(Asset.project_id == project_id)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    return query.order_by(Asset.created_at.desc()).all()


@router.post("", response_model=AssetOut, status_code=201, summary="上传素材")
async def upload_asset(
    project_id: str,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Asset:
    _get_project(db, project_id, current)
    original = file.filename or "素材"
    ext = Path(original).suffix.lower()
    content = await file.read()

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        asset_type = "image"
    elif ext in (".mp4", ".mov", ".avi", ".mkv"):
        asset_type = "video"
    elif ext in (".mp3", ".wav", ".m4a", ".ogg"):
        asset_type = "audio"
    elif ext in (".dwg", ".rvt", ".skp", ".fbx", ".obj"):
        asset_type = "model"
    else:
        asset_type = "document"

    key = f"projects/{project_id}/assets/{uuid.uuid4().hex}{ext}"
    storage.save(key, content)

    asset = Asset(
        project_id=project_id,
        name=name or original,
        asset_type=asset_type,
        source="upload",
        file_key=key,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/ai-image", status_code=202, summary="AI 生成图片（按分镜）")
def generate_image(
    project_id: str,
    shot_id: str = Form(...),
    prompt: str | None = Form(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = _get_shot(db, project_id, shot_id)
    task = create_render_task(
        db,
        project_id=project_id,
        shot_id=shot_id,
        task_type="gen_image",
        params={"shot_id": shot_id, "project_id": project_id, "prompt": prompt or shot.visual_prompt or ""},
        message="AI 生成画面中…",
    )
    dispatch(db, task=task, async_func=gen_image_task, sync_func=gen_image_sync)
    return {"task_id": task.id, "status": task.status}


@router.post("/ai-tts", status_code=202, summary="AI 配音（按分镜）")
def generate_tts(
    project_id: str,
    shot_id: str = Form(...),
    voice_name: str = Form("onyx"),
    speed: float = Form(1.0),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = _get_shot(db, project_id, shot_id)
    task = create_render_task(
        db,
        project_id=project_id,
        shot_id=shot_id,
        task_type="gen_tts",
        params={
            "shot_id": shot_id,
            "project_id": project_id,
            "text": shot.narration or "配音文本",
            "voice_name": voice_name,
            "speed": speed,
        },
        message="AI 配音生成中…",
    )
    dispatch(db, task=task, async_func=gen_tts_task, sync_func=gen_tts_sync)
    return {"task_id": task.id, "status": task.status}


@router.post("/ai-video", status_code=202, summary="AI 生成视频（按分镜）")
def generate_video(
    project_id: str,
    shot_id: str = Form(...),
    prompt: str | None = Form(None),
    duration: float = Form(5.0),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    _get_project(db, project_id, current)
    shot = _get_shot(db, project_id, shot_id)
    task = create_render_task(
        db,
        project_id=project_id,
        shot_id=shot_id,
        task_type="gen_video",
        params={
            "shot_id": shot_id,
            "project_id": project_id,
            "prompt": prompt or shot.video_prompt or shot.visual_prompt or "工程演示视频",
            "duration": duration,
        },
        message="AI 生成视频中…",
    )
    dispatch(db, task=task, async_func=gen_video_task, sync_func=gen_video_sync)
    return {"task_id": task.id, "status": task.status}


@router.patch("/{asset_id}", response_model=AssetOut, summary="更新素材")
def update_asset(
    project_id: str,
    asset_id: str,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Asset:
    _get_project(db, project_id, current)
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        raise NotFoundError("素材不存在")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(asset, field, value)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=204, summary="删除素材")
def delete_asset(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current)
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        raise NotFoundError("素材不存在")
    db.delete(asset)
    db.commit()
