"""从专业视频创建可复用 AI 视频模板。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("video_generation_templates")}
    additions = [
        ("category", sa.String(64), True),
        ("tags", sa.JSON(), True),
        ("prompt_recipe", sa.JSON(), True),
        ("preview_asset_id", sa.String(36), True),
        ("cover_asset_id", sa.String(36), True),
        ("scope", sa.String(16), False, "organization"),
        ("status", sa.String(16), False, "published"),
        ("source_video_asset_id", sa.String(36), True),
        ("clip_start_seconds", sa.Float(), True),
        ("clip_end_seconds", sa.Float(), True),
        ("first_frame_asset_id", sa.String(36), True),
        ("middle_frame_asset_id", sa.String(36), True),
        ("last_frame_asset_id", sa.String(36), True),
        ("source_license_confirmed", sa.Boolean(), False, False),
    ]
    for item in additions:
        name, column_type, nullable, *default = item
        if name in columns:
            continue
        kwargs = {"nullable": nullable}
        if default:
            kwargs["server_default"] = sa.text(str(default[0]).lower()) if isinstance(default[0], bool) else str(default[0])
        op.add_column("video_generation_templates", sa.Column(name, column_type, **kwargs))

    if not inspector.has_table("video_template_drafts"):
        op.create_table(
            "video_template_drafts",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("source_video_asset_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="uploaded"),
            sa.Column("clip_start_seconds", sa.Float(), nullable=True),
            sa.Column("clip_end_seconds", sa.Float(), nullable=True),
            sa.Column("middle_seconds", sa.Float(), nullable=True),
            sa.Column("first_frame_asset_id", sa.String(36), nullable=True),
            sa.Column("middle_frame_asset_id", sa.String(36), nullable=True),
            sa.Column("last_frame_asset_id", sa.String(36), nullable=True),
            sa.Column("prompt_recipe", sa.JSON(), nullable=True),
            sa.Column("analysis_warnings", sa.JSON(), nullable=True),
            sa.Column("intent", sa.Text(), nullable=True),
            sa.Column("preview_job_id", sa.String(36), nullable=True),
            sa.Column("preview_asset_id", sa.String(36), nullable=True),
            sa.Column("template_id", sa.String(36), nullable=True),
            sa.Column("source_license_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_video_asset_id"], ["assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["first_frame_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["middle_frame_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["last_frame_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["preview_asset_id"], ["assets.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_template_drafts_project_id", "video_template_drafts", ["project_id"])
        op.create_index("ix_video_template_drafts_source_video_asset_id", "video_template_drafts", ["source_video_asset_id"])
        op.create_index("ix_video_template_drafts_status", "video_template_drafts", ["status"])
        op.create_index("ix_video_template_drafts_preview_job_id", "video_template_drafts", ["preview_job_id"])
        op.create_index("ix_video_template_drafts_template_id", "video_template_drafts", ["template_id"])


def downgrade() -> None:
    op.drop_table("video_template_drafts")
