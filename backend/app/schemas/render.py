"""渲染 Schema：预设、任务、版本、遮罩、源图上传。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel

OperationType = Literal["render", "inpaint", "outpaint", "upscale", "color_grade"]


# ---------- RenderPreset ----------
class RenderPresetOut(TimestampedModel):
    name: str
    description: str | None
    category: str | None
    preview_image: str | None
    default_positive_prompt: str | None
    default_negative_prompt: str | None
    recommended_aspect_ratio: str
    recommended_structure_strength: int
    is_system: bool
    is_enabled: bool
    created_by: str | None
    sort_order: int
    source_preset_id: str | None


class RenderPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    category: str | None = None
    default_positive_prompt: str | None = None
    default_negative_prompt: str | None = None
    recommended_aspect_ratio: str = "16:9"
    recommended_structure_strength: int = 85
    is_system: bool = False
    is_enabled: bool = True


class RenderPresetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    default_positive_prompt: str | None = None
    default_negative_prompt: str | None = None
    recommended_aspect_ratio: str | None = None
    recommended_structure_strength: int | None = None
    is_enabled: bool | None = None


class RenderPresetDuplicateRequest(BaseModel):
    preset_id: str


# ---------- 源图上传 ----------
class SourceImageMeta(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_software: str = Field(default="Revit")
    project_stage: str | None = None
    camera_angle: str = Field(default="建筑人视")
    is_original_model_shot: bool = True
    license_note: str | None = None


class SourceImageOut(TimestampedModel):
    project_id: str
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
    color_mode: str | None
    sha256: str | None
    source_software: str | None
    camera_angle: str | None
    is_original_model_shot: bool
    is_duplicate: bool = False
    duplicate_asset_id: str | None = None


# ---------- RenderJob ----------
class RenderTaskCreate(BaseModel):
    source_asset_id: str
    preset_id: str | None = None
    operation_type: OperationType = "render"
    positive_prompt: str = ""
    negative_prompt: str | None = None
    aspect_ratio: str = "16:9"
    output_width: int | None = None
    output_height: int | None = None
    variant_count: int = Field(default=2, ge=1, le=4)
    structure_strength: int = Field(default=85, ge=0, le=100)
    creativity: float = Field(default=0.5, ge=0, le=1)
    seed: int | None = None
    # 由后端按当前 Adapter 写入真实 Provider；客户端不应伪造来源。
    provider: str | None = None
    model_name: str | None = None
    preserve_logo: bool = True
    preserve_text: bool = True
    preserve_roads: bool = True
    preserve_building_shape: bool = True
    preserve_equipment: bool = True
    custom_constraints: list[str] | None = None
    mask_asset_id: str | None = None
    idempotency_key: str | None = None
    # 概念创意图（管理员标记）
    is_conceptual: bool = False
    concept_note: str | None = None


class RenderTaskOut(BaseModel):
    id: str
    project_id: str
    source_asset_id: str | None
    preset_id: str | None
    operation_type: str
    positive_prompt: str | None
    negative_prompt: str | None
    aspect_ratio: str
    output_width: int | None
    output_height: int | None
    variant_count: int
    structure_strength: int
    creativity: float
    seed: int | None
    provider: str
    model_name: str | None
    status: str
    progress: int
    error_message: str | None
    estimated_cost: float
    actual_cost: float
    currency: str
    is_conceptual: bool
    started_at: str | None
    completed_at: str | None
    created_at: Any = None
    version_count: int = 0


class RenderVersionOut(TimestampedModel):
    render_job_id: str | None
    source_asset_id: str | None
    result_asset_id: str | None
    version_number: int
    provider: str
    model_name: str | None
    seed: int | None
    generation_type: str
    prompt_snapshot: dict | None
    negative_prompt_snapshot: dict | None
    parameter_snapshot: dict | None
    quality_metrics: dict | None
    quality_status: str
    is_selected: bool
    selected_by: str | None
    selected_at: str | None
    is_deleted: bool


class MaskUploadOut(BaseModel):
    asset_id: str
    width: int
    height: int
    file_key: str


# ---------- 操作请求 ----------
class CompareRequest(BaseModel):
    source_asset_id: str
    version_ids: list[str] = Field(min_length=1)


class InpaintRequest(BaseModel):
    source_asset_id: str
    mask_asset_id: str
    positive_prompt: str = ""
    variant_count: int = Field(default=1, ge=1, le=4)
    seed: int | None = None
    idempotency_key: str | None = None


class OutpaintRequest(BaseModel):
    source_asset_id: str
    positive_prompt: str = ""
    target_ratio: str = "16:9"
    output_width: int | None = None
    output_height: int | None = None
    variant_count: int = Field(default=1, ge=1, le=4)
    seed: int | None = None
    idempotency_key: str | None = None


class UpscaleRequest(BaseModel):
    source_asset_id: str
    scale: int = 2
    idempotency_key: str | None = None
