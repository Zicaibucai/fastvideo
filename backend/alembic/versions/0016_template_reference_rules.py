"""保存已发布模板的完整参考帧规则。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("video_generation_templates")}
    additions = [
        ("reference_frame_asset_ids", sa.JSON()),
        ("reference_frame_times", sa.JSON()),
        ("reference_frame_count", sa.Integer()),
    ]
    for name, column_type in additions:
        if name not in columns:
            op.add_column("video_generation_templates", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    op.drop_column("video_generation_templates", "reference_frame_count")
    op.drop_column("video_generation_templates", "reference_frame_times")
    op.drop_column("video_generation_templates", "reference_frame_asset_ids")
