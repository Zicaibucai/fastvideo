"""协作目标解析：校验评论/待办/审核目标确实属于当前项目（防跨项目访问）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.asset import Asset
from app.models.audio_version import AudioVersion
from app.models.collaboration import (
    TARGET_TYPE_AUDIO_VERSION,
    TARGET_TYPE_EXPORT_TASK,
    TARGET_TYPE_FACT,
    TARGET_TYPE_FACTS,
    TARGET_TYPE_PROJECT,
    TARGET_TYPE_RENDER_VERSION,
    TARGET_TYPE_SCORING_POINT,
    TARGET_TYPE_SHOT,
    TARGET_TYPE_STORYBOARD,
    TARGET_TYPE_VIDEO_GEN_VERSION,
    TARGET_TYPE_VIDEO_PROJECT,
    TARGET_TYPE_VIDEO_SEGMENT,
)
from app.models.export_task import ExportTask
from app.models.extracted_fact import ExtractedFact
from app.models.project import Project
from app.models.render_job import RenderJob
from app.models.render_version import RenderVersion
from app.models.scoring_point import ScoringPoint
from app.models.storyboard_shot import StoryboardShot
from app.models.video_generation import VideoGenerationJob, VideoGenerationVersion
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment

COMMENTABLE_TARGET_TYPES = (
    TARGET_TYPE_PROJECT,
    TARGET_TYPE_FACTS,
    TARGET_TYPE_FACT,
    TARGET_TYPE_SCORING_POINT,
    TARGET_TYPE_STORYBOARD,
    TARGET_TYPE_SHOT,
    TARGET_TYPE_RENDER_VERSION,
    TARGET_TYPE_VIDEO_GEN_VERSION,
    TARGET_TYPE_AUDIO_VERSION,
    TARGET_TYPE_VIDEO_PROJECT,
    TARGET_TYPE_VIDEO_SEGMENT,
    TARGET_TYPE_EXPORT_TASK,
)


def _fact_label(fact: ExtractedFact) -> str:
    meta = fact.metadata_json or {}
    return f"工程参数·{meta.get('label') or fact.fact_type or '参数'}"


def resolve_target(
    db: Session,
    project_id: str,
    target_type: str,
    target_id: str | None,
) -> tuple[object | None, str]:
    """解析协作目标，返回 (实体或 None, 显示定位)。目标不属于项目时抛 404。"""
    if target_type == TARGET_TYPE_PROJECT:
        project = db.get(Project, project_id)
        if project is None:
            raise NotFoundError("项目不存在")
        return project, project.name

    if target_type == TARGET_TYPE_FACTS:
        return None, "工程信息（整体）"

    if target_type == TARGET_TYPE_STORYBOARD:
        return None, "解说词与分镜（整份文稿）"

    if target_type == TARGET_TYPE_FACT:
        fact = db.get(ExtractedFact, target_id or "")
        if not fact or fact.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return fact, _fact_label(fact)

    if target_type == TARGET_TYPE_SCORING_POINT:
        sp = db.get(ScoringPoint, target_id or "")
        if not sp or sp.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return sp, f"评分点·{sp.title or sp.id[:8]}"

    if target_type == TARGET_TYPE_SHOT:
        shot = db.get(StoryboardShot, target_id or "")
        if not shot or shot.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return shot, f"分镜 {shot.sequence}·{shot.title or '未命名'}"

    if target_type == TARGET_TYPE_RENDER_VERSION:
        version = db.get(RenderVersion, target_id or "")
        job = db.get(RenderJob, version.render_job_id) if version and version.render_job_id else None
        if not version or not job or job.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return version, f"画面版本 V{version.version_number}"

    if target_type == TARGET_TYPE_VIDEO_GEN_VERSION:
        version = db.get(VideoGenerationVersion, target_id or "")
        job = db.get(VideoGenerationJob, version.video_job_id) if version else None
        if not version or not job or job.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return version, f"AI 视频版本 V{version.version_number}"

    if target_type == TARGET_TYPE_AUDIO_VERSION:
        version = db.get(AudioVersion, target_id or "")
        if not version or version.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return version, f"配音版本 V{version.version_number}"

    if target_type == TARGET_TYPE_VIDEO_PROJECT:
        vp = db.get(VideoProject, target_id or "")
        if not vp or vp.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return vp, f"视频工程·{vp.name}"

    if target_type == TARGET_TYPE_VIDEO_SEGMENT:
        seg = db.get(VideoSegment, target_id or "")
        vp = db.get(VideoProject, seg.video_project_id) if seg else None
        if not seg or not vp or vp.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return seg, f"视频分段 {seg.sequence}"

    if target_type == TARGET_TYPE_EXPORT_TASK:
        task = db.get(ExportTask, target_id or "")
        if not task or task.project_id != project_id:
            raise NotFoundError("评论目标不存在或不属于当前项目")
        return task, f"导出任务 {task.id[:8]}（{task.mode}）"

    raise NotFoundError(f"不支持的协作目标类型：{target_type}")
