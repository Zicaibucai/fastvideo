"""AI 视频生成 Schema（Phase 6/7：Seedance 图片驱动视频分镜）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel

GenerationMode = Literal["image_to_video", "first_last_frame_video"]


# ---------- 模板 ----------
class VideoGenerationTemplateOut(TimestampedModel):
    name: str
    description: str | None
    applicable_modes: list | None
    default_positive_prompt: str | None
    default_negative_prompt: str | None
    recommended_duration: int
    recommended_aspect_ratio: str
    recommended_resolution: str
    recommended_camera_motion: str | None
    default_arch_constraints: list | None
    is_system: bool
    is_enabled: bool
    created_by: str | None
    sort_order: int
    source_template_id: str | None


class VideoGenerationTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    applicable_modes: list[GenerationMode] = ["image_to_video"]
    default_positive_prompt: str | None = None
    default_negative_prompt: str | None = None
    recommended_duration: int = Field(default=5, ge=2, le=15)
    recommended_aspect_ratio: str = "adaptive"
    recommended_resolution: str = "720p"
    recommended_camera_motion: str | None = None
    default_arch_constraints: list[str] | None = None
    is_enabled: bool = True


class VideoGenerationTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    applicable_modes: list[GenerationMode] | None = None
    default_positive_prompt: str | None = None
    default_negative_prompt: str | None = None
    recommended_duration: int | None = None
    recommended_aspect_ratio: str | None = None
    recommended_resolution: str | None = None
    recommended_camera_motion: str | None = None
    default_arch_constraints: list[str] | None = None
    is_enabled: bool | None = None


# ---------- 任务 ----------
class VideoGenerationJobCreate(BaseModel):
    storyboard_shot_id: str | None = None
    generation_mode: GenerationMode = "image_to_video"
    first_frame_asset_id: str
    last_frame_asset_id: str | None = None
    template_id: str | None = None
    # 视频 Provider 与模型（seedance / minimax；留空用全局默认）
    provider: str | None = None
    model_name: str | None = None
    # 独立视频提示词（不使用 narration/visual_prompt/image_prompt）
    positive_prompt: str = ""
    negative_prompt: str | None = None
    duration: int = Field(default=5, ge=2, le=15)
    aspect_ratio: str = "adaptive"
    resolution: str = "720p"
    seed: int | None = None
    generate_audio: bool = False
    constraints_enabled: bool = True
    idempotency_key: str | None = None


class VideoGenerationJobOut(BaseModel):
    id: str
    project_id: str
    storyboard_shot_id: str | None
    generation_mode: str
    first_frame_asset_id: str | None
    last_frame_asset_id: str | None
    template_id: str | None
    positive_prompt: str | None
    negative_prompt: str | None
    architecture_constraints: list | None
    constraints_enabled: bool
    provider: str
    model_name: str | None
    duration: int
    aspect_ratio: str
    resolution: str
    seed: int | None
    generate_audio: bool
    watermark: bool
    provider_task_id: str | None
    status: str
    progress: int
    error_message: str | None
    elapsed_seconds: float | None
    result_asset_id: str | None
    result_url: str | None
    parameter_snapshot: dict | None
    created_by: str | None
    started_at: str | None
    completed_at: str | None
    created_at: Any = None
    version_count: int = 0


class VideoGenerationVersionOut(BaseModel):
    id: str
    video_job_id: str
    result_asset_id: str | None
    result_url: str | None
    version_number: int
    provider: str
    model_name: str | None
    seed: int | None
    generation_mode: str
    prompt_snapshot: dict | None
    negative_prompt_snapshot: dict | None
    parameter_snapshot: dict | None
    first_frame_asset_id: str | None
    last_frame_asset_id: str | None
    template_id: str | None
    is_selected: bool
    selected_by: str | None
    selected_at: str | None
    bound_shot_id: str | None
    bound_shot_title: str | None
    is_deleted: bool
    created_at: Any = None


# ---------- 操作请求 ----------
class BindToShotRequest(BaseModel):
    shot_id: str


class ConstraintCheckRequest(BaseModel):
    text: str = ""


class ConstraintCheckResult(BaseModel):
    conflicts: list[str]
    blocked: bool


class SelectVersionRequest(BaseModel):
    pass


# ---------- 提示词大师 ----------
class PromptMasterRequest(BaseModel):
    first_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None
    reference_asset_ids: list[str] | None = None
    template_id: str | None = None
    intent: str | None = None
    generation_mode: GenerationMode = "image_to_video"


class PromptMasterResult(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    mode: str
    is_mock: bool = False


# ---------- 参考帧 ----------
class ReferenceImageOut(BaseModel):
    id: str
    name: str
    asset_type: str
    source: str
    file_key: str | None
    thumbnail_key: str | None
    url: str | None
    file_size: int
    width: int | None
    height: int | None
    aspect_ratio: str | None
    created_at: Any = None
