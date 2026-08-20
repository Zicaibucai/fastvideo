"""分镜/解说词 Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel


class ShotVersion(BaseModel):
    revision: int
    narration: str
    visual_prompt: str | None = None
    visual_type: str | None = None
    created_at: str
    source: str = "ai"  # ai | manual


class SourceReference(BaseModel):
    documentId: str
    documentName: str
    page: int | None = None
    locationLabel: str | None = None
    quote: str | None = None


class StoryboardShotCreate(BaseModel):
    project_id: str
    sequence: int = 1
    title: str | None = None
    section: str | None = None
    narration: str | None = None
    duration_seconds: float | None = None
    source_page: int | None = None
    visual_type: str | None = None
    visual_description: str | None = None
    image_prompt: str | None = None
    video_prompt: str | None = None
    keywords: list[str] | None = None
    source_references: list | None = None
    scoring_point_ids: list[str] | None = None
    fact_check_status: str | None = None


class StoryboardShotUpdate(BaseModel):
    sequence: int | None = None
    title: str | None = None
    section: str | None = None
    narration: str | None = None
    duration_seconds: float | None = None
    visual_prompt: str | None = None
    visual_type: str | None = None
    visual_description: str | None = None
    image_prompt: str | None = None
    video_prompt: str | None = None
    keywords: list[str] | None = None
    source_references: list | None = None
    scoring_point_ids: list[str] | None = None
    fact_check_status: str | None = None
    source_model_asset_id: str | None = None
    render_version_id: str | None = None
    visual_review_status: str | None = None
    source_page: int | None = None
    status: str | None = None


class StoryboardShotOut(TimestampedModel):
    project_id: str
    sequence: int
    title: str | None
    section: str | None
    narration: str | None
    duration_seconds: float | None
    source_page: int | None
    visual_prompt: str | None
    visual_type: str | None
    visual_description: str | None
    image_prompt: str | None
    video_prompt: str | None
    keywords: list | None
    source_references: list | None
    scoring_point_ids: list | None
    fact_check_status: str | None
    image_asset_id: str | None
    video_asset_id: str | None
    audio_asset_id: str | None
    tts_voice_id: str | None
    video_clip_key: str | None
    source_model_asset_id: str | None
    render_version_id: str | None
    visual_review_status: str | None
    visual_history: list | None
    narration_hash: str | None = None
    narration_prev_hash: str | None = None
    narration_updated_at: str | None = None
    status: str
    versions: list | None


class NarrationGenerateRequest(BaseModel):
    """批量生成解说词（智能拆解）。"""

    project_id: str
    section_count: int = Field(default=10, ge=1, le=30, description="目标分镜数量")
    tone: str = Field(default="专业庄重", description="解说风格")
    target_duration_seconds: int = Field(default=300, ge=60, le=1800, description="视频目标时长（秒）")
    video_purpose: str | None = Field(default="投标答辩", description="视频用途")
    aspect_ratio: str = Field(default="16:9", description="画面比例")
    focus_scoring_points: list[str] | None = None
    include_company_intro: bool = True
    include_construction_simulation: bool = True
    chars_per_minute: int = Field(default=260, ge=120, le=400, description="每分钟参考字数")


class ShotReorderRequest(BaseModel):
    """分镜排序。"""

    shot_ids: list[str]


class ShotRegenerateRequest(BaseModel):
    shot_id: str
    prompt_hint: str | None = None


class StoryboardSummary(BaseModel):
    project_summary: str
    total_duration_seconds: int
    total_narration_characters: int
    unverified_facts: list[str]
    shots: list[StoryboardShotOut]
    scoring_coverage_rate: float | None = None
    duration_gap_seconds: int = 0
