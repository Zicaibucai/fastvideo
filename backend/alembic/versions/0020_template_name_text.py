"""Allow descriptive system video template names longer than 128 characters."""

from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL needs an explicit type change for existing installations.
    # SQLite's initial schema is generated from current metadata, and its
    # ALTER COLUMN syntax is not portable, so leave it unchanged there.
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "video_generation_templates",
            "name",
            existing_type=sa.String(length=128),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "video_generation_templates",
            "name",
            existing_type=sa.Text(),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
