"""add video_segments & video project track config

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-13

新增（Phase 5 多分段视频合成）：
- video_segments 视频分段表
- video_projects 扩展（字幕样式/音乐轨/Logo/片头片尾/品牌色/导出模式/时间轴快照）
- export_tasks 扩展（mode / srt_key / report_key / timeline_snapshot）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
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
    # ---------- video_segments ----------
    if not _has_table("video_segments"):
        op.create_table(
            "video_segments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("video_project_id", sa.String(length=36), nullable=False),
            sa.Column("storyboard_shot_id", sa.String(length=36), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("visual_asset_id", sa.String(length=36), nullable=True),
            sa.Column("audio_version_id", sa.String(length=36), nullable=True),
            sa.Column("duration", sa.Float(), nullable=False),
            sa.Column("is_locked", sa.Boolean(), nullable=False),
            sa.Column("visual_motion", sa.String(length=24), nullable=False),
            sa.Column("fit_mode", sa.String(length=16), nullable=False),
            sa.Column("transition_type", sa.String(length=24), nullable=False),
            sa.Column("transition_duration", sa.Float(), nullable=False),
            sa.Column("subtitle_enabled", sa.Boolean(), nullable=False),
            sa.Column("volume", sa.Float(), nullable=False),
            sa.Column("render_status", sa.String(length=16), nullable=False),
            sa.Column("render_progress", sa.Integer(), nullable=False),
            sa.Column("output_key", sa.String(length=1024), nullable=True),
            sa.Column("input_hash", sa.String(length=64), nullable=True),
            sa.Column("needs_rebuild", sa.Boolean(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("rendered_at", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["storyboard_shot_id"], ["storyboard_shots.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_segments_video_project_id", "video_segments", ["video_project_id"])
        op.create_index("ix_video_segments_storyboard_shot_id", "video_segments", ["storyboard_shot_id"])
        op.create_index("ix_video_segments_input_hash", "video_segments", ["input_hash"])

    # ---------- video_projects 扩展 ----------
    _add_column_if_missing("video_projects", sa.Column("subtitle_style", sa.JSON(), nullable=True))
    _add_column_if_missing("video_projects", sa.Column("music_tracks", sa.JSON(), nullable=True))
    _add_column_if_missing("video_projects", sa.Column("logo_config", sa.JSON(), nullable=True))
    _add_column_if_missing("video_projects", sa.Column("open_config", sa.JSON(), nullable=True))
    _add_column_if_missing("video_projects", sa.Column("close_config", sa.JSON(), nullable=True))
    _add_column_if_missing("video_projects", sa.Column("brand_color", sa.String(length=16), nullable=False, server_default=sa.text("'#1E3A5F'")))
    _add_column_if_missing("video_projects", sa.Column("export_mode", sa.String(length=16), nullable=False, server_default=sa.text("'demo'")))
    _add_column_if_missing("video_projects", sa.Column("timeline_snapshot", sa.JSON(), nullable=True))

    # ---------- export_tasks 扩展 ----------
    _add_column_if_missing("export_tasks", sa.Column("mode", sa.String(length=16), nullable=False, server_default=sa.text("'demo'")))
    _add_column_if_missing("export_tasks", sa.Column("srt_key", sa.String(length=1024), nullable=True))
    _add_column_if_missing("export_tasks", sa.Column("report_key", sa.String(length=1024), nullable=True))
    _add_column_if_missing("export_tasks", sa.Column("timeline_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in ("timeline_snapshot", "export_mode", "brand_color", "close_config",
                "open_config", "logo_config", "music_tracks", "subtitle_style"):
        _drop_column_if_exists("video_projects", col)
    for col in ("timeline_snapshot", "report_key", "srt_key", "mode"):
        _drop_column_if_exists("export_tasks", col)
    if _has_table("video_segments"):
        op.drop_table("video_segments")
