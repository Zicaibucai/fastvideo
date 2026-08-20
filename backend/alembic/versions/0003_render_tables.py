"""add render preset/job/version tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13

新增：
- render_presets / render_jobs / render_versions 三张表
- assets 增加 sha256/thumbnail/来源软件/相机角度等元数据列
- storyboard_shots 增加 source_model_asset_id / render_version_id / visual_review_status / visual_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(table)]
    return column in cols


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _drop_column_if_exists(table: str, column: str) -> None:
    if _has_column(table, column):
        op.drop_column(table, column)


def upgrade() -> None:
    # ---------- render_presets ----------
    if not _has_table("render_presets"):
        op.create_table(
            "render_presets",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=64), nullable=True),
            sa.Column("preview_image", sa.String(length=1024), nullable=True),
            sa.Column("default_positive_prompt", sa.Text(), nullable=True),
            sa.Column("default_negative_prompt", sa.Text(), nullable=True),
            sa.Column("recommended_aspect_ratio", sa.String(length=16), nullable=False),
            sa.Column("recommended_structure_strength", sa.Integer(), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("source_preset_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    # ---------- render_jobs ----------
    if not _has_table("render_jobs"):
        op.create_table(
            "render_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("storyboard_shot_id", sa.String(length=36), nullable=True),
            sa.Column("source_asset_id", sa.String(length=36), nullable=True),
            sa.Column("preset_id", sa.String(length=36), nullable=True),
            sa.Column("operation_type", sa.String(length=16), nullable=False),
            sa.Column("positive_prompt", sa.Text(), nullable=True),
            sa.Column("negative_prompt", sa.Text(), nullable=True),
            sa.Column("aspect_ratio", sa.String(length=16), nullable=False),
            sa.Column("output_width", sa.Integer(), nullable=True),
            sa.Column("output_height", sa.Integer(), nullable=True),
            sa.Column("variant_count", sa.Integer(), nullable=False),
            sa.Column("structure_strength", sa.Integer(), nullable=False),
            sa.Column("creativity", sa.Float(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=True),
            sa.Column("preserve_logo", sa.Boolean(), nullable=False),
            sa.Column("preserve_text", sa.Boolean(), nullable=False),
            sa.Column("preserve_roads", sa.Boolean(), nullable=False),
            sa.Column("preserve_building_shape", sa.Boolean(), nullable=False),
            sa.Column("preserve_equipment", sa.Boolean(), nullable=False),
            sa.Column("custom_constraints", sa.JSON(), nullable=True),
            sa.Column("mask_asset_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("celery_task_id", sa.String(length=64), nullable=True),
            sa.Column("idempotency_key", sa.String(length=64), nullable=True),
            sa.Column("provider_task_id", sa.String(length=64), nullable=True),
            sa.Column("estimated_cost", sa.Float(), nullable=False),
            sa.Column("actual_cost", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("started_at", sa.String(length=32), nullable=True),
            sa.Column("completed_at", sa.String(length=32), nullable=True),
            sa.Column("is_conceptual", sa.Boolean(), nullable=False),
            sa.Column("concept_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["storyboard_shot_id"], ["storyboard_shots.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_render_jobs_project_id", "render_jobs", ["project_id"])
        op.create_index("ix_render_jobs_storyboard_shot_id", "render_jobs", ["storyboard_shot_id"])
        op.create_index("ix_render_jobs_source_asset_id", "render_jobs", ["source_asset_id"])
        op.create_index("ix_render_jobs_idempotency_key", "render_jobs", ["idempotency_key"])

    # ---------- render_versions ----------
    if not _has_table("render_versions"):
        op.create_table(
            "render_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("render_job_id", sa.String(length=36), nullable=True),
            sa.Column("source_asset_id", sa.String(length=36), nullable=True),
            sa.Column("result_asset_id", sa.String(length=36), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=True),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("generation_type", sa.String(length=16), nullable=False),
            sa.Column("prompt_snapshot", sa.JSON(), nullable=True),
            sa.Column("negative_prompt_snapshot", sa.JSON(), nullable=True),
            sa.Column("parameter_snapshot", sa.JSON(), nullable=True),
            sa.Column("quality_metrics", sa.JSON(), nullable=True),
            sa.Column("quality_status", sa.String(length=16), nullable=False),
            sa.Column("is_selected", sa.Boolean(), nullable=False),
            sa.Column("selected_by", sa.String(length=64), nullable=True),
            sa.Column("selected_at", sa.String(length=32), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("deleted_by", sa.String(length=64), nullable=True),
            sa.Column("deleted_at", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["render_job_id"], ["render_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["result_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_render_versions_render_job_id", "render_versions", ["render_job_id"])

    # ---------- assets 新字段 ----------
    _add_column_if_missing("assets", sa.Column("sha256", sa.String(length=64), nullable=True))
    _add_column_if_missing("assets", sa.Column("thumbnail_key", sa.String(length=1024), nullable=True))
    _add_column_if_missing("assets", sa.Column("color_mode", sa.String(length=16), nullable=True))
    _add_column_if_missing("assets", sa.Column("aspect_ratio", sa.String(length=16), nullable=True))
    _add_column_if_missing("assets", sa.Column("is_original_model_shot", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    _add_column_if_missing("assets", sa.Column("source_software", sa.String(length=32), nullable=True))
    _add_column_if_missing("assets", sa.Column("project_stage", sa.String(length=64), nullable=True))
    _add_column_if_missing("assets", sa.Column("camera_angle", sa.String(length=32), nullable=True))
    _add_column_if_missing("assets", sa.Column("license_note", sa.Text(), nullable=True))
    _add_column_if_missing("assets", sa.Column("is_ai_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_missing("assets", sa.Column("is_conceptual", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_missing("assets", sa.Column("ai_disclaimer", sa.Text(), nullable=True))
    try:
        sa.Index("ix_assets_sha256", "assets", "sha256").create(op.get_bind())
    except Exception:
        pass

    # ---------- storyboard_shots 新字段 ----------
    _add_column_if_missing("storyboard_shots", sa.Column("source_model_asset_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("render_version_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("visual_review_status", sa.String(length=16), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("visual_history", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in ("visual_history", "visual_review_status", "render_version_id", "source_model_asset_id"):
        _drop_column_if_exists("storyboard_shots", col)

    try:
        sa.Index("ix_assets_sha256", "assets", "sha256").drop(op.get_bind())
    except Exception:
        pass
    for col in ("ai_disclaimer", "is_conceptual", "is_ai_generated", "license_note",
                "camera_angle", "project_stage", "source_software", "is_original_model_shot",
                "aspect_ratio", "color_mode", "thumbnail_key", "sha256"):
        _drop_column_if_exists("assets", col)

    for table in ("render_versions", "render_jobs", "render_presets"):
        if _has_table(table):
            op.drop_table(table)
