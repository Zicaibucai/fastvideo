"""记录投标项目最后一次进入时间。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("projects", "last_entered_at"):
        op.add_column(
            "projects",
            sa.Column("last_entered_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_projects_last_entered_at", "projects", ["last_entered_at"])


def downgrade() -> None:
    if _has_column("projects", "last_entered_at"):
        op.drop_index("ix_projects_last_entered_at", table_name="projects")
        op.drop_column("projects", "last_entered_at")
