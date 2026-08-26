"""统一 AI Provider 配置与业务环节绑定。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("ai_configurations"):
        op.create_table(
            "ai_configurations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("scope", sa.String(32), nullable=False, unique=True, server_default="global"),
            sa.Column("providers", sa.JSON(), nullable=True),
            sa.Column("stages", sa.JSON(), nullable=True),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_by", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_configurations"):
        op.drop_table("ai_configurations")
