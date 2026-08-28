"""导入所有模型，确保 Base.metadata 完整注册（Alembic 自动生成依赖于此）。"""

from app.models.base import Base, BaseModel, TimestampMixin, UUIDPKMixin, uuid_str  # noqa: F401
from app.models.user import User
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.models.document_upload_session import DocumentUploadSession
from app.models.document_page import DocumentPage
from app.models.document_chunk import DocumentChunk
from app.models.extracted_fact import ExtractedFact
from app.models.scoring_point import ScoringPoint
from app.models.storyboard_shot import StoryboardShot
from app.models.narration_run import NarrationRun, NarrationEvidenceBatch, NarrationEvidence
from app.models.narration_beat import NarrationBeat
from app.models.asset import Asset
from app.models.audio_version import AudioVersion
from app.models.audit_log import AuditLog
from app.models.pronunciation import PronunciationProfile, PronunciationRule
from app.models.render_task import RenderTask
from app.models.render_preset import RenderPreset
from app.models.render_job import RenderJob
from app.models.render_version import RenderVersion
from app.models.voice_template import VoiceTemplate
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.models.video_generation import (
    VideoGenerationJob,
    VideoGenerationTemplate,
    VideoGenerationVersion,
    VideoTemplateDraft,
)
from app.models.export_task import ExportTask
from app.models.ai_configuration import AIConfiguration
from app.models.collaboration import (
    Notification,
    ProjectComment,
    ProjectInvitation,
    ProjectMember,
    ProjectWorkItem,
    ReviewDecision,
    ReviewRequest,
)

__all__ = [
    "Base",
    "BaseModel",
    "TimestampMixin",
    "UUIDPKMixin",
    "uuid_str",
    "User",
    "Project",
    "SourceDocument",
    "DocumentUploadSession",
    "DocumentPage",
    "DocumentChunk",
    "ExtractedFact",
    "ScoringPoint",
    "StoryboardShot",
    "NarrationRun",
    "NarrationEvidenceBatch",
    "NarrationEvidence",
    "NarrationBeat",
    "Asset",
    "AudioVersion",
    "PronunciationProfile",
    "PronunciationRule",
    "AuditLog",
    "RenderTask",
    "RenderPreset",
    "RenderJob",
    "RenderVersion",
    "VoiceTemplate",
    "VideoProject",
    "VideoSegment",
    "VideoGenerationTemplate",
    "VideoGenerationJob",
    "VideoGenerationVersion",
    "VideoTemplateDraft",
    "ExportTask",
    "AIConfiguration",
    "ProjectMember",
    "ProjectInvitation",
    "ProjectComment",
    "ProjectWorkItem",
    "ReviewRequest",
    "ReviewDecision",
    "Notification",
]
