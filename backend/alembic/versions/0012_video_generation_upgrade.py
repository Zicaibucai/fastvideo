"""视频生成多参考图、版本变体与视频分段节奏策略。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0001 使用当前 ORM metadata 建表，升级到历史版本时这些字段可能已经存在。
    # 迁移保持幂等，避免新数据库或开发数据库重复加列失败。
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def add_column_if_missing(table: str, column: sa.Column) -> None:
        existing = {item["name"] for item in inspector.get_columns(table)}
        if column.name not in existing:
            op.add_column(table, column)

    add_column_if_missing("video_generation_jobs", sa.Column("reference_asset_ids", sa.JSON(), nullable=True))
    add_column_if_missing("video_generation_jobs", sa.Column("variant_group_id", sa.String(36), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("video_generation_jobs")}
    if "ix_video_generation_jobs_variant_group_id" not in indexes:
        op.create_index("ix_video_generation_jobs_variant_group_id", "video_generation_jobs", ["variant_group_id"])
    add_column_if_missing("video_generation_versions", sa.Column("reference_asset_ids", sa.JSON(), nullable=True))
    add_column_if_missing("video_segments", sa.Column("time_adaptation", sa.String(24), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def drop_column_if_present(table: str, name: str) -> None:
        existing = {item["name"] for item in inspector.get_columns(table)}
        if name in existing:
            op.drop_column(table, name)

    drop_column_if_present("video_segments", "time_adaptation")
    drop_column_if_present("video_generation_versions", "reference_asset_ids")
    indexes = {index["name"] for index in inspector.get_indexes("video_generation_jobs")}
    if "ix_video_generation_jobs_variant_group_id" in indexes:
        op.drop_index("ix_video_generation_jobs_variant_group_id", table_name="video_generation_jobs")
    drop_column_if_present("video_generation_jobs", "variant_group_id")
    drop_column_if_present("video_generation_jobs", "reference_asset_ids")
