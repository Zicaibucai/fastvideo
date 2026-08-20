"""Phase 4 配音相关 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedModel


# ============================================================
# 配音模板
# ============================================================

class VoiceTemplateCreate(BaseModel):
    name: str = Field(..., max_length=128)
    description: str | None = None
    voice_provider: str = "mock"
    voice_name: str | None = None
    provider_voice_id: str | None = None
    model_name: str | None = None
    language: str = "zh-CN"
    gender: str | None = None  # 兼容旧字段，映射到 gender_style
    gender_style: str = "male"
    age_style: str | None = None
    speaking_style: str | None = None
    style: str | None = None
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    pause_strength: float = 1.0
    emotion: str | None = None
    sample_rate: int = 48000
    audio_format: str = "wav"
    pronunciation_profile_id: str | None = None
    authorization_type: str = "provider_builtin"
    authorization_status: str = "approved"
    authorization_note: str | None = None
    authorization_expire_at: datetime | None = None
    preview_text: str | None = None
    is_default: bool = False
    is_system: bool = False
    is_enabled: bool = True
    sort_order: int = 0


class VoiceTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    voice_provider: str | None = None
    voice_name: str | None = None
    provider_voice_id: str | None = None
    model_name: str | None = None
    language: str | None = None
    gender_style: str | None = None
    age_style: str | None = None
    speaking_style: str | None = None
    style: str | None = None
    speed: float | None = None
    pitch: float | None = None
    volume: float | None = None
    pause_strength: float | None = None
    emotion: str | None = None
    sample_rate: int | None = None
    audio_format: str | None = None
    pronunciation_profile_id: str | None = None
    authorization_type: str | None = None
    authorization_status: str | None = None
    authorization_note: str | None = None
    authorization_expire_at: datetime | None = None
    preview_text: str | None = None
    is_default: bool | None = None
    is_system: bool | None = None
    is_enabled: bool | None = None
    sort_order: int | None = None


class VoiceTemplateOut(TimestampedModel):
    project_id: str | None
    name: str
    description: str | None
    voice_provider: str
    voice_name: str
    provider_voice_id: str | None
    model_name: str | None
    language: str
    gender: str
    gender_style: str
    age_style: str | None
    speaking_style: str | None
    style: str | None
    speed: float
    pitch: float
    volume: float
    pause_strength: float
    emotion: str | None
    sample_rate: int
    audio_format: str
    pronunciation_profile_id: str | None
    authorization_type: str
    authorization_status: str
    authorization_note: str | None
    authorization_expire_at: datetime | None
    preview_asset_id: str | None
    preview_text: str | None
    is_default: bool
    is_system: bool
    is_enabled: bool
    sort_order: int
    created_by: str | None


# ============================================================
# 发音词典
# ============================================================

class PronunciationRuleCreate(BaseModel):
    source_text: str = Field(..., max_length=500)
    spoken_text: str = Field(..., max_length=500)
    language: str = "zh-CN"
    rule_type: str = "literal"
    priority: int = 100
    is_regex: bool = False
    scope: str = "project"  # system | enterprise | project


class PronunciationRuleUpdate(BaseModel):
    source_text: str | None = None
    spoken_text: str | None = None
    language: str | None = None
    rule_type: str | None = None
    priority: int | None = None
    is_regex: bool | None = None
    enabled: bool | None = None
    scope: str | None = None


class PronunciationRuleOut(TimestampedModel):
    project_id: str | None
    profile_id: str | None
    source_text: str
    spoken_text: str
    language: str
    rule_type: str
    priority: int
    is_regex: bool
    enabled: bool
    scope: str
    created_by: str | None
    conflict_hint: str | None


class PronunciationProfileOut(TimestampedModel):
    project_id: str | None
    name: str
    description: str | None
    language: str
    scope: str
    is_system: bool
    is_enabled: bool
    created_by: str | None
    rule_count: int = 0


class PronunciationTestIn(BaseModel):
    text: str


class PronunciationTestOut(BaseModel):
    original_text: str
    normalized_text: str
    pronunciation_snapshot: list[dict]
    matched_rules: list[dict]
    warnings: list[str]


class PronunciationImportIn(BaseModel):
    rules: list[dict]


# ============================================================
# 配音生成
# ============================================================

class VoiceEstimateRequest(BaseModel):
    shot_id: str
    voice_template_id: str | None = None


class VoiceGenerateRequest(BaseModel):
    shot_id: str
    voice_template_id: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch: float | None = None
    volume: float | None = None
    emotion: str | None = None
    pause_strength: float | None = None
    normalized_text_override: str | None = None
    seed: int | None = None
    output_formats: list[str] | None = None
    idempotency_key: str | None = None


class VoiceBatchRequest(BaseModel):
    shot_ids: list[str] | None = None
    voice_template_id: str | None = None
    speed: float | None = None
    pause_strength: float | None = None
    skip_empty: bool = True
    regenerate_stale: bool = True
    max_concurrency: int = Field(default=3, ge=1, le=8)
    continue_on_error: bool = True
    output_formats: list[str] | None = None
    idempotency_key: str | None = None
    # 时长适配策略：natural（保持自然语速）| adjust（微调语速）
    duration_strategy: str = "natural"


class VoiceJobRetryRequest(BaseModel):
    task_id: str


class VoiceJobCancelRequest(BaseModel):
    task_id: str


# ============================================================
# 字幕
# ============================================================

class SubtitleSegmentUpdate(BaseModel):
    sequence: int
    start_ms: int = Field(ge=0)
    end_ms: int


class SubtitleUpdateRequest(BaseModel):
    segments: list[SubtitleSegmentUpdate]


# ============================================================
# 版本选择 / 删除
# ============================================================

class VoiceSelectRequest(BaseModel):
    version_id: str


class VoiceRestoreRequest(BaseModel):
    version_id: str
