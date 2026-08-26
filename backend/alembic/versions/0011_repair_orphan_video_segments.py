"""将历史悬空视频位置归档并解除无效分镜引用。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # 旧 SQLite 曾关闭外键，历史数据可能保留已删除分镜 ID。
    # 这些位置无法安全映射到新分镜，只能归档并清空悬空引用；对应素材和导出文件不删除。
    bind.execute(sa.text(
        "UPDATE video_segments "
        "SET storyboard_shot_id = NULL, render_status = 'skipped', needs_rebuild = 1 "
        "WHERE storyboard_shot_id IS NOT NULL "
        "AND storyboard_shot_id NOT IN (SELECT id FROM storyboard_shots)"
    ))


def downgrade() -> None:
    # 无法恢复原本不存在的分镜 ID，保持数据安全，不反向写入悬空引用。
    pass
