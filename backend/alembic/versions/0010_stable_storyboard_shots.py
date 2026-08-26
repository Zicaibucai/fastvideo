"""保持分镜 ID 稳定并支持归档旧分镜。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("storyboard_shots", "is_active"):
        op.add_column("storyboard_shots", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        op.create_index("ix_storyboard_shots_is_active", "storyboard_shots", ["is_active"])
    if not _has_column("storyboard_shots", "revision"):
        op.add_column("storyboard_shots", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    if _has_column("storyboard_shots", "revision"):
        op.drop_column("storyboard_shots", "revision")
    if _has_column("storyboard_shots", "is_active"):
        op.drop_index("ix_storyboard_shots_is_active", table_name="storyboard_shots")
        op.drop_column("storyboard_shots", "is_active")
