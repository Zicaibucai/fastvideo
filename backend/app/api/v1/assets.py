"""素材库路由：上传、列表、删除 + AI 生成（图片/视频/TTS）。"""

from __future__ import annotations

import uuid
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
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
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.project import Project
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.schemas.asset import AssetCreate, AssetOut, AssetUpdate
from app.schemas.common import Message
from app.services.video_project_service import backfill_video_render_assets
from app.services.video_template_service import inspect_source_video
from app.services.task_runner import create_render_task, dispatch

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["素材库"])
logger = get_logger(__name__)


def _get_project(db: Session, project_id: str, user: User, permission: str = PERM_MEDIA_VIEW) -> Project:
    """统一项目访问：成员校验 + 细粒度权限（非成员 404，权限不足 403）。"""
    return get_project_access(db, project_id, user, permission).project


@router.post("/ai-image", response_model=dict, status_code=202, summary="为分镜生成 AI 图片")
def generate_ai_image(
    project_id: str,
    shot_id: str = Form(...),
    prompt: str = Form("建筑工程场景"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    """兼容旧版分镜画面入口；生成的是图片素材，不是 AI 视频绑定。"""
    _get_project(db, project_id, current, PERM_MEDIA_EDIT)
    shot = db.get(StoryboardShot, shot_id)
    if not shot or shot.project_id != project_id or not shot.is_active:
        raise NotFoundError("分镜不存在")
    task = create_render_task(
        db,
        project_id=project_id,
        shot_id=shot_id,
        task_type="gen_image",
        params={"project_id": project_id, "shot_id": shot_id, "prompt": prompt},
        message="AI 生成画面中…",
    )
    from app.tasks.assets import gen_image_sync, gen_image_task

    dispatch(db, task=task, async_func=gen_image_task, sync_func=gen_image_sync)
    db.refresh(task)
    return {"task_id": task.id, "status": task.status}


@router.get("", response_model=list[AssetOut], summary="素材列表")
def list_assets(
    project_id: str,
    asset_type: str | None = None,
    source: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[Asset]:
    _get_project(db, project_id, current, PERM_MEDIA_VIEW)
    backfill_video_render_assets(db, project_id)
    query = db.query(Asset).filter(Asset.project_id == project_id)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if source:
        query = query.filter(Asset.source == source)
    assets = query.order_by(Asset.created_at.desc()).all()
    # 视频素材可能是旧版本上传的，尚未写入时长/分辨率。素材库打开时
    # 仅对缺少元数据的视频做一次轻量 ffprobe，供模板选择器展示基础说明。
    if asset_type == "video":
        changed = False
        for asset in assets:
            if not asset.file_key or (asset.duration_seconds is not None and asset.width and asset.height):
                continue
            try:
                inspect_source_video(db, asset)
                changed = True
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("asset_video_metadata_probe_failed", asset_id=asset.id, error=str(exc))
        if changed:
            db.commit()
    return assets


@router.post("", response_model=AssetOut, status_code=201, summary="上传素材")
async def upload_asset(
    project_id: str,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Asset:
    _get_project(db, project_id, current, PERM_MEDIA_VIEW)
    original = file.filename or "素材"
    ext = Path(original).suffix.lower()
    content = await file.read()

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        asset_type = "image"
    elif ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
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


@router.get("/{asset_id}/first-frame", response_model=None, summary="视频起始帧")
def get_video_first_frame(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    """返回视频素材的第一帧，作为视频工程选材时的可视化确认。"""
    _get_project(db, project_id, current, PERM_MEDIA_VIEW)
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        raise NotFoundError("素材不存在")
    if asset.asset_type != "video" or not asset.file_key:
        raise HTTPException(status_code=422, detail="只有视频素材支持起始帧预览")

    if asset.thumbnail_key and storage.exists(asset.thumbnail_key):
        return Response(storage.load(asset.thumbnail_key), media_type="image/jpeg")

    if not storage.exists(asset.file_key):
        raise NotFoundError("视频文件不存在")
    source_path: str | None = None
    try:
        source_path = storage.local_path(asset.file_key)
        with tempfile.TemporaryDirectory(prefix="fastvideo_first_frame_") as tmp:
            frame = Path(tmp) / "first.jpg"
            proc = subprocess.run(
                [
                    settings.ffmpeg_binary,
                    "-y",
                    "-i", source_path,
                    "-frames:v", "1",
                    "-vf", "scale=640:-2",
                    "-q:v", "3",
                    str(frame),
                ],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0 or not frame.exists():
                raise HTTPException(status_code=422, detail="无法读取该视频的起始帧")
            frame_data = frame.read_bytes()
    finally:
        if source_path:
            storage.release_local_path(source_path)

    thumbnail_key = f"projects/{project_id}/assets/{asset.id}_first_frame.jpg"
    storage.save(thumbnail_key, frame_data)
    asset.thumbnail_key = thumbnail_key
    db.commit()
    return Response(frame_data, media_type="image/jpeg")


@router.patch("/{asset_id}", response_model=AssetOut, summary="更新素材")
def update_asset(
    project_id: str,
    asset_id: str,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Asset:
    _get_project(db, project_id, current, PERM_MEDIA_EDIT)
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
    _get_project(db, project_id, current, PERM_MEDIA_EDIT)
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        raise NotFoundError("素材不存在")
    db.delete(asset)
    db.commit()
