"""Add database uniqueness for project-scoped idempotency keys."""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _remove_duplicate_keys(table: str) -> None:
    # Keep the earliest request and discard only duplicate idempotency rows
    # before creating the unique indexes. NULL keys are intentionally ignored.
    op.execute(
        f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY project_id, idempotency_key
                           ORDER BY created_at ASC, id ASC
                       ) AS duplicate_rank
                FROM {table}
                WHERE idempotency_key IS NOT NULL
            ) duplicates
            WHERE duplicate_rank > 1
        )
        """
    )


def upgrade() -> None:
    _remove_duplicate_keys("render_jobs")
    _remove_duplicate_keys("video_generation_jobs")
    op.create_index(
        "uq_render_jobs_project_idempotency",
        "render_jobs",
        ["project_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_video_jobs_project_idempotency",
        "video_generation_jobs",
        ["project_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_video_jobs_project_idempotency", table_name="video_generation_jobs")
    op.drop_index("uq_render_jobs_project_idempotency", table_name="render_jobs")
