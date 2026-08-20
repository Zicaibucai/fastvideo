"""add voice/pronunciation/audio_version/audit tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-13

新增（Phase 4 配音）：
- voice_templates 扩展（描述/音色/风格/参数/授权/启用状态）
- audio_versions 配音版本表
- pronunciation_profiles / pronunciation_rules 发音词典表
- audit_logs 审计日志表
- render_tasks.parent_task_id 批量父任务
- storyboard_shots 解说词变化追踪（narration_hash 等）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
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


def _create_index_if_missing(table: str, column: str) -> None:
    name = f"ix_{table}_{column}"
    bind = op.get_bind()
    try:
        idxs = [i["name"] for i in sa.inspect(bind).get_indexes(table)]
        if name not in idxs:
            op.create_index(name, table, [column])
    except Exception:
        pass


def upgrade() -> None:
    # ---------- voice_templates 扩展 ----------
    for col in [
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider_voice_id", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False, server_default=sa.text("'zh-CN'")),
        sa.Column("gender_style", sa.String(length=16), nullable=False, server_default=sa.text("'male'")),
        sa.Column("age_style", sa.String(length=16), nullable=True),
        sa.Column("speaking_style", sa.String(length=32), nullable=True),
        sa.Column("volume", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("pause_strength", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("emotion", sa.String(length=32), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default=sa.text("48000")),
        sa.Column("audio_format", sa.String(length=16), nullable=False, server_default=sa.text("'wav'")),
        sa.Column("pronunciation_profile_id", sa.String(length=36), nullable=True),
        sa.Column("authorization_type", sa.String(length=32), nullable=False, server_default=sa.text("'provider_builtin'")),
        sa.Column("authorization_status", sa.String(length=32), nullable=False, server_default=sa.text("'approved'")),
        sa.Column("authorization_note", sa.Text(), nullable=True),
        sa.Column("authorization_expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=64), nullable=True),
    ]:
        _add_column_if_missing("voice_templates", col)

    # ---------- audio_versions ----------
    if not _has_table("audio_versions"):
        op.create_table(
            "audio_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("storyboard_shot_id", sa.String(length=36), nullable=False),
            sa.Column("voice_template_id", sa.String(length=36), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("original_text_snapshot", sa.Text(), nullable=True),
            sa.Column("normalized_text_snapshot", sa.Text(), nullable=True),
            sa.Column("pronunciation_snapshot", sa.JSON(), nullable=True),
            sa.Column("narration_hash", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=True),
            sa.Column("voice_id", sa.String(length=64), nullable=True),
            sa.Column("speed", sa.Float(), nullable=False),
            sa.Column("pitch", sa.Float(), nullable=False),
            sa.Column("volume", sa.Float(), nullable=False),
            sa.Column("emotion", sa.String(length=32), nullable=True),
            sa.Column("pause_strength", sa.Float(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("target_duration_seconds", sa.Float(), nullable=True),
            sa.Column("estimated_duration_seconds", sa.Float(), nullable=True),
            sa.Column("actual_duration_seconds", sa.Float(), nullable=True),
            sa.Column("duration_difference", sa.Float(), nullable=True),
            sa.Column("duration_difference_ratio", sa.Float(), nullable=True),
            sa.Column("duration_status", sa.String(length=32), nullable=False),
            sa.Column("audio_asset_id", sa.String(length=36), nullable=True),
            sa.Column("wav_asset_id", sa.String(length=36), nullable=True),
            sa.Column("mp3_asset_id", sa.String(length=36), nullable=True),
            sa.Column("subtitle_data", sa.JSON(), nullable=True),
            sa.Column("waveform_data", sa.JSON(), nullable=True),
            sa.Column("provider_metadata", sa.JSON(), nullable=True),
            sa.Column("quality_metrics", sa.JSON(), nullable=True),
            sa.Column("quality_status", sa.String(length=16), nullable=False),
            sa.Column("authorization_snapshot", sa.JSON(), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False),
            sa.Column("is_stale", sa.Boolean(), nullable=False),
            sa.Column("stale_reason", sa.String(length=255), nullable=True),
            sa.Column("is_selected", sa.Boolean(), nullable=False),
            sa.Column("selected_by", sa.String(length=64), nullable=True),
            sa.Column("selected_at", sa.String(length=32), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("deleted_by", sa.String(length=64), nullable=True),
            sa.Column("deleted_at", sa.String(length=32), nullable=True),
            sa.Column("estimated_cost", sa.Float(), nullable=False),
            sa.Column("actual_cost", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["storyboard_shot_id"], ["storyboard_shots.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["audio_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audio_versions_project_id", "audio_versions", ["project_id"])
        op.create_index("ix_audio_versions_storyboard_shot_id", "audio_versions", ["storyboard_shot_id"])
        op.create_index("ix_audio_versions_narration_hash", "audio_versions", ["narration_hash"])

    # ---------- pronunciation_profiles ----------
    if not _has_table("pronunciation_profiles"):
        op.create_table(
            "pronunciation_profiles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("language", sa.String(length=16), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_pronunciation_profiles_project_id", "pronunciation_profiles", ["project_id"])

    # ---------- pronunciation_rules ----------
    if not _has_table("pronunciation_rules"):
        op.create_table(
            "pronunciation_rules",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("profile_id", sa.String(length=36), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("source_text", sa.String(length=500), nullable=False),
            sa.Column("spoken_text", sa.String(length=500), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=False),
            sa.Column("rule_type", sa.String(length=16), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("is_regex", sa.Boolean(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("conflict_hint", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["profile_id"], ["pronunciation_profiles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_pronunciation_rules_profile_id", "pronunciation_rules", ["profile_id"])
        op.create_index("ix_pronunciation_rules_project_id", "pronunciation_rules", ["project_id"])

    # ---------- audit_logs ----------
    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("user_name", sa.String(length=64), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=64), nullable=True),
            sa.Column("entity_id", sa.String(length=36), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
        op.create_index("ix_audit_logs_project_id", "audit_logs", ["project_id"])
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # ---------- render_tasks.parent_task_id ----------
    _add_column_if_missing("render_tasks", sa.Column("parent_task_id", sa.String(length=36), nullable=True))
    _create_index_if_missing("render_tasks", "parent_task_id")

    # ---------- storyboard_shots 解说词变化追踪 ----------
    _add_column_if_missing("storyboard_shots", sa.Column("narration_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("narration_prev_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("narration_updated_at", sa.String(length=32), nullable=True))


def downgrade() -> None:
    for col in ("narration_updated_at", "narration_prev_hash", "narration_hash"):
        _drop_column_if_exists("storyboard_shots", col)
    _drop_column_if_exists("render_tasks", "parent_task_id")

    for table in ("audit_logs", "pronunciation_rules", "pronunciation_profiles", "audio_versions"):
        if _has_table(table):
            op.drop_table(table)

    for col in ("created_by", "is_enabled", "authorization_expire_at", "authorization_note",
                "authorization_status", "authorization_type", "pronunciation_profile_id",
                "audio_format", "sample_rate", "emotion", "pause_strength", "volume",
                "speaking_style", "age_style", "gender_style", "language", "model_name",
                "provider_voice_id", "description"):
        _drop_column_if_exists("voice_templates", col)
