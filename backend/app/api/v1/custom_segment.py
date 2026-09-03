"""自定义合成路由：自选视频 + 自输字幕/TTS 直接合成，不绑定分镜。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.asset import Asset
from app.models.user import User
from app.schemas.video import (
    CUSTOM_SEGMENT_AUDIO_MODES,
    CUSTOM_SEGMENT_FIT_MODES,
    CUSTOM_SEGMENT_TIME_ADAPTATIONS,
    CustomSegmentIn,
)
from app.services.permissions import get_project_access, PERM_VIDEO_EDIT
from app.services.task_runner import create_render_task, dispatch
from app.tasks.custom_segment import custom_segment_sync, custom_segment_task

router = APIRouter(tags=["自定义合成"])


@router.post("/projects/{project_id}/custom-segments", status_code=202, summary="创建自定义合成任务")
def create_custom_segment(
    project_id: str,
    payload: CustomSegmentIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    get_project_access(db, project_id, current, PERM_VIDEO_EDIT)

    if payload.fps not in (24, 25, 30):
        raise ConflictError("fps 仅支持 24/25/30")
    if payload.audio_mode not in CUSTOM_SEGMENT_AUDIO_MODES:
        raise ConflictError("audio_mode 仅支持 mute / keep_original / tts")
    if payload.audio_mode == "tts":
        if not payload.voice_template_id:
            raise ConflictError("TTS 配音需要选择配音模板")
        if not (payload.subtitle_text or "").strip():
            raise ConflictError("TTS 配音需要填写字幕/朗读文本")
    if payload.time_adaptation not in CUSTOM_SEGMENT_TIME_ADAPTATIONS:
        raise ConflictError("不支持的时长适配策略")
    if payload.fit_mode not in CUSTOM_SEGMENT_FIT_MODES:
        raise ConflictError("不支持的适配模式")

    asset = db.get(Asset, payload.visual_asset_id)
    if not asset or asset.project_id != project_id:
        raise NotFoundError("视频素材不存在")
    if asset.asset_type != "video" or not asset.file_key:
        raise ConflictError("自定义合成只能选择视频素材")

    params = payload.model_dump()
    params["task_id"] = None
    task = create_render_task(
        db,
        project_id=project_id,
        task_type="custom_segment_render",
        params=params,
        message="自定义合成排队中…",
    )
    task.params = {**(task.params or {}), "task_id": task.id}
    db.commit()
    db.refresh(task)
    dispatch(db, task=task, async_func=custom_segment_task, sync_func=custom_segment_sync)
    db.refresh(task)
    return {"task_id": task.id, "status": task.status}
