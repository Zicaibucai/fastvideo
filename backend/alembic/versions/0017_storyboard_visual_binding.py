"""补齐分镜画面渲染绑定的素材字段。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("storyboard_shots")}
    if "image_asset_id" not in columns:
        op.add_column("storyboard_shots", sa.Column("image_asset_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("storyboard_shots")}
    if "image_asset_id" in columns:
        op.drop_column("storyboard_shots", "image_asset_id")
