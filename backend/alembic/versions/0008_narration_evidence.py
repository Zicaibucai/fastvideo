"""add long document narration evidence and beat timeline tables

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )


def upgrade() -> None:
    if _has_table("document_chunks") and not _has_column("document_chunks", "sequence"):
        op.add_column("document_chunks", sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"))
        op.create_index("ix_document_chunks_sequence", "document_chunks", ["sequence"])
        op.create_index("ix_document_chunks_document_sequence", "document_chunks", ["document_id", "sequence"])

    if not _has_table("narration_runs"):
        op.create_table(
            "narration_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("generation_mode", sa.String(length=32), nullable=False),
            sa.Column("prompt_version", sa.String(length=64), nullable=False),
            sa.Column("params", sa.JSON(), nullable=True),
            sa.Column("progress", sa.JSON(), nullable=True),
            sa.Column("total_batches", sa.Integer(), nullable=False),
            sa.Column("completed_batches", sa.Integer(), nullable=False),
            sa.Column("evidence_count", sa.Integer(), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            *_timestamps(),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_narration_runs_project_id", "narration_runs", ["project_id"])
        op.create_index("ix_narration_runs_status", "narration_runs", ["status"])

    if not _has_table("narration_evidence_batches"):
        op.create_table(
            "narration_evidence_batches",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("batch_index", sa.Integer(), nullable=False),
            sa.Column("chunk_start_sequence", sa.Integer(), nullable=False),
            sa.Column("chunk_end_sequence", sa.Integer(), nullable=False),
            sa.Column("chunk_ids", sa.JSON(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("cache_key", sa.String(length=128), nullable=True),
            sa.Column("content_chars", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            *_timestamps(),
            sa.ForeignKeyConstraint(["run_id"], ["narration_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_narration_evidence_batches_run_id", "narration_evidence_batches", ["run_id"])
        op.create_index("ix_narration_evidence_batches_document_id", "narration_evidence_batches", ["document_id"])
        op.create_index("ix_narration_evidence_batches_content_hash", "narration_evidence_batches", ["content_hash"])
        op.create_index("ix_narration_evidence_batches_cache_key", "narration_evidence_batches", ["cache_key"])
    elif not _has_column("narration_evidence_batches", "cache_key"):
        op.add_column("narration_evidence_batches", sa.Column("cache_key", sa.String(length=128), nullable=True))
        op.create_index("ix_narration_evidence_batches_cache_key", "narration_evidence_batches", ["cache_key"])

    if not _has_table("narration_evidence"):
        op.create_table(
            "narration_evidence",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("batch_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("topic", sa.String(length=64), nullable=False),
            sa.Column("fact", sa.Text(), nullable=False),
            sa.Column("parameters", sa.JSON(), nullable=True),
            sa.Column("construction_actions", sa.JSON(), nullable=True),
            sa.Column("sequence_context", sa.Text(), nullable=True),
            sa.Column("source_reference", sa.JSON(), nullable=True),
            sa.Column("source_chunk_ids", sa.JSON(), nullable=True),
            sa.Column("fact_check_status", sa.String(length=16), nullable=False),
            sa.Column("review_status", sa.String(length=16), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["run_id"], ["narration_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["batch_id"], ["narration_evidence_batches.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, column in (
            ("run_id", "run_id"),
            ("batch_id", "batch_id"),
            ("project_id", "project_id"),
            ("document_id", "document_id"),
            ("topic", "topic"),
            ("review_status", "review_status"),
            ("fingerprint", "fingerprint"),
        ):
            op.create_index(f"ix_narration_evidence_{name}", "narration_evidence", [column])

    if not _has_table("narration_beats"):
        op.create_table(
            "narration_beats",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("shot_id", sa.String(length=36), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("shot_sequence", sa.Integer(), nullable=False),
            sa.Column("narration", sa.Text(), nullable=False),
            sa.Column("start_time", sa.Float(), nullable=False),
            sa.Column("end_time", sa.Float(), nullable=False),
            sa.Column("evidence_ids", sa.JSON(), nullable=True),
            sa.Column("source_references", sa.JSON(), nullable=True),
            sa.Column("fact_check_status", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["shot_id"], ["storyboard_shots.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_narration_beats_project_id", "narration_beats", ["project_id"])
        op.create_index("ix_narration_beats_shot_id", "narration_beats", ["shot_id"])
        op.create_index("ix_narration_beats_sequence", "narration_beats", ["sequence"])


def downgrade() -> None:
    for table in ("narration_beats", "narration_evidence", "narration_evidence_batches", "narration_runs"):
        if _has_table(table):
            op.drop_table(table)
    if _has_column("document_chunks", "sequence"):
        op.drop_column("document_chunks", "sequence")
