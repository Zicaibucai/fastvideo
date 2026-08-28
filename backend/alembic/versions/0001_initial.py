"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 使用 Base.metadata 自动创建全部表（便于维护，避免手写数百行）。
    # 注意必须使用迁移连接（op.get_bind()）而不是全局 engine，
    # 否则在非默认数据库（如测试临时库）上建表会落到错误的库中。
    from app.core.database import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.core.database import Base

    Base.metadata.drop_all(bind=op.get_bind())
