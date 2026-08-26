"""AI 视频生成 Schema（Phase 6/7：Seedance 图片驱动视频分镜）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel

GenerationMode = Literal["image_to_video", "first_last_frame_video", "multi_reference_video"]


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
    category: str | None = None
    tags: list | None = None
    prompt_recipe: dict | None = None
    preview_asset_id: str | None = None
    cover_asset_id: str | None = None
    preview_file_key: str | None = None
    cover_file_key: str | None = None
    scope: str = Field(default="organization", pattern="^(personal|organization)$")
    status: str = "published"
    source_video_asset_id: str | None = None
    clip_start_seconds: float | None = None
    clip_end_seconds: float | None = None
    first_frame_asset_id: str | None = None
    middle_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None
    first_frame_file_key: str | None = None
    middle_frame_file_key: str | None = None
    last_frame_file_key: str | None = None
    reference_frame_asset_ids: list[str] = []
    reference_frame_times: list[float] = []
    reference_frame_count: int | None = None
    source_license_confirmed: bool = False


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
    category: str | None = None
    tags: list[str] | None = None
    prompt_recipe: dict | None = None
    preview_asset_id: str | None = None
    cover_asset_id: str | None = None
    reference_frame_asset_ids: list[str] | None = None
    reference_frame_times: list[float] | None = None
    reference_frame_count: int | None = Field(default=None, ge=1, le=9)
    scope: str = "organization"


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
    category: str | None = None
    tags: list[str] | None = None
    prompt_recipe: dict | None = None
    preview_asset_id: str | None = None
    cover_asset_id: str | None = None
    reference_frame_asset_ids: list[str] | None = None
    reference_frame_times: list[float] | None = None
    reference_frame_count: int | None = Field(default=None, ge=1, le=9)
    scope: str | None = Field(default=None, pattern="^(personal|organization)$")


# ---------- 任务 ----------
class VideoGenerationJobCreate(BaseModel):
    generation_mode: GenerationMode = "image_to_video"
    first_frame_asset_id: str
    last_frame_asset_id: str | None = None
    # Seedance 2.0 多参考图，顺序即镜头参考顺序，最多 9 张。
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=9)
    template_id: str | None = None
    # 提示词大师生成的结构化配方；即使未发布模板，也要把运镜/时间轴/建筑约束传给视频模型。
    prompt_recipe: dict | None = None
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
    # 用户已在确认窗口中确认本次提示词中的结构变化风险。
    structure_conflict_confirmed: bool = False
    idempotency_key: str | None = None


class VideoGenerationJobOut(BaseModel):
    id: str
    project_id: str
    generation_mode: str
    first_frame_asset_id: str | None
    last_frame_asset_id: str | None
    reference_asset_ids: list[str] = []
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
    asset_status: str = "processing"
    result_url: str | None
    quality_report: dict | None = None
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
    name: str | None
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
    reference_asset_ids: list[str] = []
    quality_report: dict | None = None
    template_id: str | None
    is_selected: bool
    selected_by: str | None
    selected_at: str | None
    is_deleted: bool
    created_at: Any = None


class VideoGenerationVersionRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


# ---------- 操作请求 ----------
class ConstraintCheckRequest(BaseModel):
    text: str = ""
    prompt_recipe: dict | None = None


class ConstraintCheckResult(BaseModel):
    conflicts: list[str]
    blocked: bool


class PromptCompileRequest(BaseModel):
    positive_prompt: str = ""
    negative_prompt: str | None = None
    prompt_recipe: dict | None = None
    template_id: str | None = None
    constraints_enabled: bool = True
    # 页面高级参数是最终输出规格；提示词中的 4K/1080p 等描述会被清理。
    resolution: str | None = None


class PromptCompileResult(BaseModel):
    positive_prompt: str
    negative_prompt: str
    provider_prompt: str
    provider_prompt_chars: int
    provider_prompt_limit: int = 2000
    prompt_recipe: dict | None = None
    conflicts: list[str] = []
    blocked: bool = False


class SelectVersionRequest(BaseModel):
    pass


# ---------- 提示词大师 ----------
class PromptMasterRequest(BaseModel):
    first_frame_asset_id: str | None = None
    middle_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None
    reference_asset_ids: list[str] | None = None
    template_id: str | None = None
    intent: str | None = None
    generation_mode: GenerationMode = "image_to_video"


class PromptMasterResult(BaseModel):
    prompt: str
    name: str | None = None
    description: str | None = None
    negative_prompt: str | None = None
    mode: str
    is_mock: bool = False
    provider: str | None = None
    model: str | None = None
    vision_used: bool = False
    warnings: list[str] = []
    recommended_duration: int | None = None
    recipe: dict | None = None


# ---------- 从专业视频创建模板 ----------
class VideoTemplateDraftCreate(BaseModel):
    source_video_asset_id: str
    name: str = Field(default="专业视频模板", min_length=1, max_length=128)
    description: str | None = None
    source_license_confirmed: bool = False


class VideoTemplateDraftClipRequest(BaseModel):
    clip_start_seconds: float = Field(ge=0)
    clip_end_seconds: float = Field(gt=0)
    # 兼容旧客户端的单个中间帧时间；新客户端传入按顺序排列的多个时间点。
    middle_seconds: float | list[float] | None = None


class VideoTemplateDraftAnalyzeRequest(BaseModel):
    intent: str | None = Field(default=None, max_length=1000)
    generation_mode: GenerationMode = "image_to_video"


class VideoTemplateDraftRecipeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    prompt_recipe: dict


class VideoTemplatePreviewRequest(BaseModel):
    provider: str | None = None
    model_name: str | None = None
    duration: int = Field(default=5, ge=2, le=15)
    aspect_ratio: str = "adaptive"
    resolution: str = "720p"
    structure_conflict_confirmed: bool = False


class VideoTemplatePublishRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    category: str = "建筑外景运镜"
    tags: list[str] = Field(default_factory=list)
    scope: str = Field(default="organization", pattern="^(personal|organization)$")


class VideoTemplateDraftOut(TimestampedModel):
    project_id: str
    source_video_asset_id: str
    source_video_name: str | None = None
    source_video_file_key: str | None = None
    source_video_duration_seconds: float | None = None
    name: str
    description: str | None
    status: str
    clip_start_seconds: float | None
    clip_end_seconds: float | None
    middle_seconds: float | None
    first_frame_asset_id: str | None
    middle_frame_asset_id: str | None
    last_frame_asset_id: str | None
    reference_frame_asset_ids: list[str] = []
    reference_frame_times: list[float] = []
    first_frame_file_key: str | None = None
    middle_frame_file_key: str | None = None
    last_frame_file_key: str | None = None
    reference_frame_file_keys: list[str] = []
    prompt_recipe: dict | None
    analysis_warnings: list | None
    intent: str | None
    preview_job_id: str | None
    preview_asset_id: str | None
    preview_file_key: str | None = None
    template_id: str | None
    source_license_confirmed: bool


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
