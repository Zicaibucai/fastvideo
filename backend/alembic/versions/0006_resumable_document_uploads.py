"""add resumable document upload sessions

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("document_upload_sessions"):
        return
    op.create_table(
        "document_upload_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("uploaded_chunks", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("temp_dir", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_upload_sessions_project_id", "document_upload_sessions", ["project_id"])
    op.create_index("ix_document_upload_sessions_user_id", "document_upload_sessions", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("document_upload_sessions"):
        op.drop_table("document_upload_sessions")
