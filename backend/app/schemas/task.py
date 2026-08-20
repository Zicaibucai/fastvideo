"""任务与状态 Schema。"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import TimestampedModel


class RenderTaskOut(TimestampedModel):
    project_id: str | None
    shot_id: str | None
    task_type: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    message: str | None
    error_message: str | None
    result: dict | None


class TaskRetryRequest(BaseModel):
    task_id: str


class TaskCancelRequest(BaseModel):
    task_id: str


class VoiceTemplateCreate(BaseModel):
    project_id: str | None = None
    name: str
    voice_provider: str = "disabled"
    voice_name: str = "onyx"
    gender: str = "male"
    style: str | None = None
    speed: float = 1.0
    pitch: float = 1.0
    preview_text: str | None = None
    is_default: bool = False


class VoiceTemplateUpdate(BaseModel):
    name: str | None = None
    voice_name: str | None = None
    gender: str | None = None
    style: str | None = None
    speed: float | None = None
    pitch: float | None = None
    preview_text: str | None = None
    is_default: bool | None = None


class VoiceTemplateOut(TimestampedModel):
    project_id: str | None
    name: str
    voice_provider: str
    voice_name: str
    gender: str
    style: str | None
    speed: float
    pitch: float
    preview_asset_id: str | None
    preview_text: str | None
    is_default: bool
    is_system: bool
    sort_order: int


class TTSGenerateRequest(BaseModel):
    shot_ids: list[str] | None = None
    voice_template_id: str | None = None
