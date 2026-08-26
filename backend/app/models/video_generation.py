"""AI 视频生成数据实体（Phase 6/7：Seedance 图片驱动视频分镜）。

三个实体：
- VideoGenerationTemplate  视频生成模板（全局表，仅供视频生成使用，与图片渲染预设隔离）
- VideoGenerationJob       视频生成任务（含完整参数快照、约束、Seedance 任务 ID）
- VideoGenerationVersion   视频结果版本（可预览/下载/选为当前结果/软删除）

设计原则：
- 每个生成任务保存完整参数快照（提示词、模板、首帧、尾帧、模型、结果版本），便于复现与切换。
- 解说词（narration/visual_prompt/image_prompt）不参与视频生成，任务只记录用户独立填写的正向提示词。
- 首尾帧模式顺序固定为 [first_frame, last_frame]。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class VideoGenerationTemplate(BaseModel):
    __tablename__ = "video_generation_templates"

    # 系统模板名称可能直接来自带描述性的中文镜头文案，不能用 128 字符硬截断。
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 适用模式：["image_to_video"] | ["first_last_frame_video"] | 两者
    applicable_modes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    default_positive_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_duration: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    recommended_aspect_ratio: Mapped[str] = mapped_column(
        String(16), default="adaptive", nullable=False
    )
    recommended_resolution: Mapped[str] = mapped_column(
        String(16), default="720p", nullable=False
    )
    recommended_camera_motion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_arch_constraints: Mapped[list | None] = mapped_column(JSON, nullable=True)

    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 企业模板复制自系统模板时记录来源
    source_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 可复用模板配方与样片来源（用户创建模板）
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompt_recipe: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    preview_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(16), default="organization", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="published", nullable=False)
    source_video_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    clip_start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    middle_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    last_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    # 模板制作时保存完整的有序参考帧规则；首/中/尾字段保留用于旧模板兼容和封面展示。
    reference_frame_asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_frame_times: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_license_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    preview_asset = relationship("Asset", foreign_keys=[preview_asset_id], lazy="selectin")
    cover_asset = relationship("Asset", foreign_keys=[cover_asset_id], lazy="selectin")
    source_video_asset = relationship("Asset", foreign_keys=[source_video_asset_id], lazy="selectin")
    first_frame_asset = relationship("Asset", foreign_keys=[first_frame_asset_id], lazy="selectin")
    middle_frame_asset = relationship("Asset", foreign_keys=[middle_frame_asset_id], lazy="selectin")
    last_frame_asset = relationship("Asset", foreign_keys=[last_frame_asset_id], lazy="selectin")


class VideoTemplateDraft(BaseModel):
    """从专业视频提炼模板的中间草稿。"""

    __tablename__ = "video_template_drafts"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_video_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="uploaded", nullable=False, index=True)
    clip_start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    middle_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    middle_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    last_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    # 用户在模板创建器中按顺序加入的参考帧（首帧之后最多 8 张）。
    reference_frame_asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_frame_times: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompt_recipe: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    preview_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    template_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_license_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project = relationship("Project")
    source_video_asset = relationship("Asset", foreign_keys=[source_video_asset_id], lazy="selectin")
    first_frame_asset = relationship("Asset", foreign_keys=[first_frame_asset_id], lazy="selectin")
    middle_frame_asset = relationship("Asset", foreign_keys=[middle_frame_asset_id], lazy="selectin")
    last_frame_asset = relationship("Asset", foreign_keys=[last_frame_asset_id], lazy="selectin")
    preview_asset = relationship("Asset", foreign_keys=[preview_asset_id], lazy="selectin")


class VideoGenerationJob(BaseModel):
    __tablename__ = "video_generation_jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_video_jobs_project_idempotency"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 旧版本遗留字段：AI 视频生成结果不与分镜建立绑定契约。
    # 视频素材只在 VideoSegment.visual_asset_id 中由视频工程选择。
    storyboard_shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # 生成模式：image_to_video | first_last_frame_video
    generation_mode: Mapped[str] = mapped_column(
        String(32), default="image_to_video", nullable=False
    )
    first_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), index=True, nullable=True
    )
    last_frame_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), index=True, nullable=True
    )
    reference_asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    variant_group_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 独立视频提示词（不使用 narration/visual_prompt/image_prompt）
    positive_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 建筑约束快照（默认启用并保存）
    architecture_constraints: Mapped[list | None] = mapped_column(JSON, nullable=True)
    constraints_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 模型与参数
    provider: Mapped[str] = mapped_column(String(32), default="seedance", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="adaptive", nullable=False)
    resolution: Mapped[str] = mapped_column(String(16), default="720p", nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generate_audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    watermark: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Provider 任务 / 状态
    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", nullable=False, index=True
    )  # queued|running|success|failed|cancelled
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(nullable=True)

    # 结果 / 幂等 / 审计
    result_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 完整参数快照（便于复现与切换）
    parameter_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project = relationship("Project")
    storyboard_shot = relationship("StoryboardShot", lazy="selectin")
    first_frame_asset = relationship(
        "Asset", foreign_keys=[first_frame_asset_id], lazy="selectin"
    )
    last_frame_asset = relationship(
        "Asset", foreign_keys=[last_frame_asset_id], lazy="selectin"
    )
    result_asset = relationship(
        "Asset", foreign_keys=[result_asset_id], lazy="selectin"
    )
    versions = relationship(
        "VideoGenerationVersion",
        back_populates="video_job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_summary_dict(self) -> dict:
        return {
            "id": self.id,
            "generation_mode": self.generation_mode,
            "status": self.status,
            "progress": self.progress,
            "provider": self.provider,
            "model_name": self.model_name,
            "seed": self.seed,
            "duration": self.duration,
            "aspect_ratio": self.aspect_ratio,
            "resolution": self.resolution,
            "generate_audio": self.generate_audio,
            "provider_task_id": self.provider_task_id,
            "error_message": self.error_message,
            "elapsed_seconds": self.elapsed_seconds,
            "version_count": len(self.versions),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VideoGenerationVersion(BaseModel):
    __tablename__ = "video_generation_versions"
    __table_args__ = (
        UniqueConstraint("video_job_id", "version_number", name="uq_video_versions_job_version"),
        UniqueConstraint("variant_group_id", "version_number", name="uq_video_versions_variant_version"),
    )

    video_job_id: Mapped[str] = mapped_column(
        ForeignKey("video_generation_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    result_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    variant_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    provider: Mapped[str] = mapped_column(String(32), default="seedance", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_mode: Mapped[str] = mapped_column(
        String(32), default="image_to_video", nullable=False
    )

    # 快照
    prompt_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    negative_prompt_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parameter_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_frame_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_frame_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reference_asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 选择状态（当前结果）
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 旧版本遗留字段，停止写入；保留数据库列以兼容已有数据迁移。
    bound_shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # 软删除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    video_job = relationship("VideoGenerationJob", back_populates="versions")
    result_asset = relationship("Asset", foreign_keys=[result_asset_id], lazy="selectin")
    bound_shot = relationship("StoryboardShot", lazy="selectin")
