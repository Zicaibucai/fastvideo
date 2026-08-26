"""支持模板草稿保存多个有序参考帧。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("video_template_drafts")}
    if "reference_frame_asset_ids" not in columns:
        op.add_column(
            "video_template_drafts",
            sa.Column("reference_frame_asset_ids", sa.JSON(), nullable=True),
        )
    if "reference_frame_times" not in columns:
        op.add_column(
            "video_template_drafts",
            sa.Column("reference_frame_times", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("video_template_drafts", "reference_frame_times")
    op.drop_column("video_template_drafts", "reference_frame_asset_ids")
