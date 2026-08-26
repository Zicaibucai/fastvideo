"""Make generated version numbers unique and monotonic per owner."""

from alembic import op
from sqlalchemy import Column, String, inspect


def _inspector():
    return inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return any(item["name"] == column for item in _inspector().get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return any(item["name"] == index for item in _inspector().get_indexes(table))


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if not _has_index(table, name):
        op.create_index(name, table, columns, unique=unique)


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _dedupe(table: str, owner_column: str, extra_where: str = "") -> None:
    op.execute(
        f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY {owner_column}, version_number
                           ORDER BY created_at ASC, id ASC
                       ) AS duplicate_rank
                FROM {table}
                WHERE {owner_column} IS NOT NULL {extra_where}
            ) duplicates
            WHERE duplicate_rank > 1
        )
        """
    )


def upgrade() -> None:
    if not _has_column("video_generation_versions", "variant_group_id"):
        op.add_column(
            "video_generation_versions",
            Column("variant_group_id", String(36), nullable=True),
        )
    _create_index(
        "ix_video_generation_versions_variant_group_id",
        "video_generation_versions",
        ["variant_group_id"],
    )
    op.execute(
        """
        UPDATE video_generation_versions
        SET variant_group_id = (
            SELECT variant_group_id
            FROM video_generation_jobs
            WHERE video_generation_jobs.id = video_generation_versions.video_job_id
        )
        """
    )

    _dedupe("audio_versions", "storyboard_shot_id")
    _dedupe("render_versions", "render_job_id")
    _dedupe("video_generation_versions", "video_job_id")
    _dedupe("video_generation_versions", "variant_group_id", " AND variant_group_id IS NOT NULL")

    _create_index(
        "uq_audio_versions_shot_version",
        "audio_versions",
        ["storyboard_shot_id", "version_number"],
        unique=True,
    )
    _create_index(
        "uq_render_versions_job_version",
        "render_versions",
        ["render_job_id", "version_number"],
        unique=True,
    )
    _create_index(
        "uq_video_versions_job_version",
        "video_generation_versions",
        ["video_job_id", "version_number"],
        unique=True,
    )
    _create_index(
        "uq_video_versions_variant_version",
        "video_generation_versions",
        ["variant_group_id", "version_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_video_versions_variant_version", table_name="video_generation_versions")
    op.drop_index("uq_video_versions_job_version", table_name="video_generation_versions")
    op.drop_index("uq_render_versions_job_version", table_name="render_versions")
    op.drop_index("uq_audio_versions_shot_version", table_name="audio_versions")
    op.drop_index("ix_video_generation_versions_variant_group_id", table_name="video_generation_versions")
    op.drop_column("video_generation_versions", "variant_group_id")
