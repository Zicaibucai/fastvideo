"""add ai video generation tables (seedance)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-14

新增（Phase 6/7：Seedance 图片驱动视频分镜）：
- video_generation_templates  视频生成模板（全局表，仅供视频生成，与图片渲染预设隔离）
- video_generation_jobs       视频生成任务（含参数快照、建筑约束、Seedance 任务 ID）
- video_generation_versions   视频结果版本（预览/下载/选为当前结果/绑定分镜/软删除）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    # ---------- video_generation_templates ----------
    if not _has_table("video_generation_templates"):
        op.create_table(
            "video_generation_templates",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("applicable_modes", sa.JSON(), nullable=True),
            sa.Column("default_positive_prompt", sa.Text(), nullable=True),
            sa.Column("default_negative_prompt", sa.Text(), nullable=True),
            sa.Column("recommended_duration", sa.Integer(), nullable=False),
            sa.Column("recommended_aspect_ratio", sa.String(length=16), nullable=False),
            sa.Column("recommended_resolution", sa.String(length=16), nullable=False),
            sa.Column("recommended_camera_motion", sa.String(length=255), nullable=True),
            sa.Column("default_arch_constraints", sa.JSON(), nullable=True),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("source_template_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    # ---------- video_generation_jobs ----------
    if not _has_table("video_generation_jobs"):
        op.create_table(
            "video_generation_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("storyboard_shot_id", sa.String(length=36), nullable=True),
            sa.Column("generation_mode", sa.String(length=32), nullable=False),
            sa.Column("first_frame_asset_id", sa.String(length=36), nullable=True),
            sa.Column("last_frame_asset_id", sa.String(length=36), nullable=True),
            sa.Column("template_id", sa.String(length=36), nullable=True),
            sa.Column("positive_prompt", sa.Text(), nullable=True),
            sa.Column("negative_prompt", sa.Text(), nullable=True),
            sa.Column("architecture_constraints", sa.JSON(), nullable=True),
            sa.Column("constraints_enabled", sa.Boolean(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=128), nullable=True),
            sa.Column("duration", sa.Integer(), nullable=False),
            sa.Column("aspect_ratio", sa.String(length=16), nullable=False),
            sa.Column("resolution", sa.String(length=16), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("generate_audio", sa.Boolean(), nullable=False),
            sa.Column("watermark", sa.Boolean(), nullable=False),
            sa.Column("provider_task_id", sa.String(length=128), nullable=True),
            sa.Column("celery_task_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("elapsed_seconds", sa.Float(), nullable=True),
            sa.Column("result_asset_id", sa.String(length=36), nullable=True),
            sa.Column("idempotency_key", sa.String(length=64), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.String(length=32), nullable=True),
            sa.Column("completed_at", sa.String(length=32), nullable=True),
            sa.Column("parameter_snapshot", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["storyboard_shot_id"], ["storyboard_shots.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["first_frame_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["last_frame_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["result_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_generation_jobs_project_id", "video_generation_jobs", ["project_id"])
        op.create_index("ix_video_generation_jobs_storyboard_shot_id", "video_generation_jobs", ["storyboard_shot_id"])
        op.create_index("ix_video_generation_jobs_first_frame_asset_id", "video_generation_jobs", ["first_frame_asset_id"])
        op.create_index("ix_video_generation_jobs_last_frame_asset_id", "video_generation_jobs", ["last_frame_asset_id"])
        op.create_index("ix_video_generation_jobs_status", "video_generation_jobs", ["status"])
        op.create_index("ix_video_generation_jobs_idempotency_key", "video_generation_jobs", ["idempotency_key"])

    # ---------- video_generation_versions ----------
    if not _has_table("video_generation_versions"):
        op.create_table(
            "video_generation_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("video_job_id", sa.String(length=36), nullable=False),
            sa.Column("result_asset_id", sa.String(length=36), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=128), nullable=True),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("generation_mode", sa.String(length=32), nullable=False),
            sa.Column("prompt_snapshot", sa.JSON(), nullable=True),
            sa.Column("negative_prompt_snapshot", sa.JSON(), nullable=True),
            sa.Column("parameter_snapshot", sa.JSON(), nullable=True),
            sa.Column("first_frame_asset_id", sa.String(length=36), nullable=True),
            sa.Column("last_frame_asset_id", sa.String(length=36), nullable=True),
            sa.Column("template_id", sa.String(length=36), nullable=True),
            sa.Column("is_selected", sa.Boolean(), nullable=False),
            sa.Column("selected_by", sa.String(length=64), nullable=True),
            sa.Column("selected_at", sa.String(length=32), nullable=True),
            sa.Column("bound_shot_id", sa.String(length=36), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("deleted_by", sa.String(length=64), nullable=True),
            sa.Column("deleted_at", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["video_job_id"], ["video_generation_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["result_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["bound_shot_id"], ["storyboard_shots.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_generation_versions_video_job_id", "video_generation_versions", ["video_job_id"])
        op.create_index("ix_video_generation_versions_bound_shot_id", "video_generation_versions", ["bound_shot_id"])


def downgrade() -> None:
    if _has_table("video_generation_versions"):
        op.drop_table("video_generation_versions")
    if _has_table("video_generation_jobs"):
        op.drop_table("video_generation_jobs")
    if _has_table("video_generation_templates"):
        op.drop_table("video_generation_templates")
