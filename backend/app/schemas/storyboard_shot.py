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
    insert_at: int | None = Field(default=None, ge=1, description="插入后的分镜序号")
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
    source_page: int | None = None
    status: str | None = None
    base_revision: int | None = Field(default=None, description="乐观锁版本，不一致返回 409")


class NarrationDocumentShotUpdate(BaseModel):
    """连续文稿模式提交的单个分镜旁白。"""

    shot_id: str
    narration: str


class NarrationDocumentUpdate(BaseModel):
    """连续文稿模式的批量保存请求。"""

    shots: list[NarrationDocumentShotUpdate] = Field(min_length=1)


class StoryboardResegmentRequest(BaseModel):
    """只重新划分现有正文，不重新编写事实内容。"""

    target_shot_count: int = Field(default=56, ge=1, le=100)
    chars_per_minute: int = Field(default=215, ge=120, le=400)
    instructions: str | None = Field(default=None, max_length=2000)


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
    source_model_asset_id: str | None = None
    render_version_id: str | None = None
    image_asset_id: str | None = None
    visual_review_status: str | None = None
    visual_history: list | None = None
    video_asset_id: str | None
    audio_asset_id: str | None
    # 当前正式配音状态，供前端准确筛选需调整分镜。
    audio_duration_status: str | None = None
    audio_quality_status: str | None = None
    audio_is_stale: bool = False
    tts_voice_id: str | None
    video_clip_key: str | None
    narration_hash: str | None = None
    narration_prev_hash: str | None = None
    narration_updated_at: str | None = None
    status: str
    is_active: bool = True
    revision: int = 1
    versions: list | None


class NarrationGenerateRequest(BaseModel):
    """批量生成解说词（智能拆解）。"""

    project_id: str
    section_count: int = Field(default=56, ge=1, le=100, description="目标视觉分镜数量")
    target_shot_count: int | None = Field(default=None, ge=1, le=100, description="目标视觉分镜数量（优先于旧 section_count）")
    tone: str = Field(default="专业庄重", description="解说风格")
    target_duration_seconds: int = Field(default=540, ge=60, le=1800, description="视频目标时长（秒）")
    video_purpose: str | None = Field(default="投标答辩", description="视频用途")
    aspect_ratio: str = Field(default="16:9", description="画面比例")
    focus_scoring_points: list[str] | None = None
    include_company_intro: bool = False
    include_construction_simulation: bool = True
    chars_per_minute: int = Field(default=215, ge=120, le=400, description="每分钟参考字数")
    generation_mode: Literal["multi_stage", "single_pass"] = "multi_stage"
    custom_requirements: str | None = Field(default=None, max_length=2000, description="本次解说词的额外写作要求")
    predefined_outline: str | None = Field(default=None, max_length=6000, description="用户预设的章节大纲")
    target_beat_count: int = Field(default=120, ge=20, le=240, description="目标旁白短句数量")
    evidence_batch_chars: int = Field(default=9000, ge=3000, le=16000, description="全文证据批次字符数")
    evidence_concurrency: int = Field(default=3, ge=1, le=8, description="证据批次并发数")
    evidence_auto_approve: bool = Field(default=True, description="是否自动通过证据审核")
    evidence_run_id: str | None = Field(default=None, description="复用已有证据运行，支持审核后继续")
    strict_fact_mode: bool = Field(default=True, description="严格事实模式")


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
