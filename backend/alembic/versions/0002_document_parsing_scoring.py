"""add document parsing & scoring tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13

新增：
- document_pages / document_chunks / extracted_facts / scoring_points 四张表
- source_documents 增加 sha256 / mime_type / is_duplicate / 统计字段等
- storyboard_shots 增加 visual_type / source_references / fact_check_status 等
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(table)]
    return column in cols


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _drop_column_if_exists(table: str, column: str) -> None:
    if _has_column(table, column):
        op.drop_column(table, column)


def upgrade() -> None:
    # ---------- document_pages ----------
    if not _has_table("document_pages"):
        op.create_table(
            "document_pages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("location_label", sa.String(length=64), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("cleaned_text", sa.Text(), nullable=True),
            sa.Column("markdown_text", sa.Text(), nullable=True),
            sa.Column("page_type", sa.String(length=16), nullable=False),
            sa.Column("extraction_method", sa.String(length=16), nullable=False),
            sa.Column("ocr_status", sa.String(length=16), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])

    # ---------- document_chunks ----------
    if not _has_table("document_chunks"):
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("heading_path", sa.String(length=512), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("token_count", sa.Integer(), nullable=False),
            sa.Column("chunk_type", sa.String(length=16), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    # ---------- extracted_facts ----------
    if not _has_table("extracted_facts"):
        op.create_table(
            "extracted_facts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=True),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("location_label", sa.String(length=64), nullable=True),
            sa.Column("fact_type", sa.String(length=64), nullable=False),
            sa.Column("fact_name", sa.String(length=255), nullable=False),
            sa.Column("fact_value", sa.Text(), nullable=False),
            sa.Column("unit", sa.String(length=64), nullable=True),
            sa.Column("source_quote", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("verification_status", sa.String(length=16), nullable=False),
            sa.Column("confirmed_by", sa.String(length=64), nullable=True),
            sa.Column("confirmed_at", sa.String(length=32), nullable=True),
            sa.Column("candidates", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_extracted_facts_project_id", "extracted_facts", ["project_id"])
        op.create_index("ix_extracted_facts_document_id", "extracted_facts", ["document_id"])
        op.create_index("ix_extracted_facts_fact_type", "extracted_facts", ["fact_type"])
        op.create_index("ix_extracted_facts_verification_status", "extracted_facts", ["verification_status"])

    # ---------- scoring_points ----------
    if not _has_table("scoring_points"):
        op.create_table(
            "scoring_points",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("score_total", sa.Float(), nullable=True),
            sa.Column("source_document_id", sa.String(length=36), nullable=True),
            sa.Column("source_page", sa.Integer(), nullable=True),
            sa.Column("source_quote", sa.Text(), nullable=True),
            sa.Column("matched_shot_ids", sa.JSON(), nullable=True),
            sa.Column("category", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_scoring_points_project_id", "scoring_points", ["project_id"])

    # ---------- source_documents 新字段 ----------
    _add_column_if_missing("source_documents", sa.Column("sha256", sa.String(length=64), nullable=True))
    _add_column_if_missing("source_documents", sa.Column("mime_type", sa.String(length=128), nullable=True))
    _add_column_if_missing("source_documents", sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_missing("source_documents", sa.Column("original_document_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("source_documents", sa.Column("total_pages", sa.Integer(), nullable=True))
    _add_column_if_missing("source_documents", sa.Column("ocr_pages", sa.Integer(), nullable=False, server_default=sa.text("0")))
    _add_column_if_missing("source_documents", sa.Column("failed_pages", sa.Integer(), nullable=False, server_default=sa.text("0")))
    _add_column_if_missing("source_documents", sa.Column("table_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    bind = op.get_bind()
    try:
        sa.Index("ix_source_documents_sha256", "source_documents", "sha256").create(bind)
    except Exception:
        pass

    # ---------- storyboard_shots 新字段 ----------
    _add_column_if_missing("storyboard_shots", sa.Column("visual_type", sa.String(length=32), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("visual_description", sa.Text(), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("image_prompt", sa.Text(), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("video_prompt", sa.Text(), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("keywords", sa.JSON(), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("source_references", sa.JSON(), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("scoring_point_ids", sa.JSON(), nullable=True))
    _add_column_if_missing("storyboard_shots", sa.Column("fact_check_status", sa.String(length=16), nullable=True))


def downgrade() -> None:
    # storyboard_shots 新字段
    for col in ("fact_check_status", "scoring_point_ids", "source_references",
                "keywords", "video_prompt", "image_prompt", "visual_description", "visual_type"):
        _drop_column_if_exists("storyboard_shots", col)

    # source_documents 新字段
    bind = op.get_bind()
    try:
        sa.Index("ix_source_documents_sha256", "source_documents", "sha256").drop(bind)
    except Exception:
        pass
    for col in ("table_count", "failed_pages", "ocr_pages", "total_pages",
                "original_document_id", "is_duplicate", "mime_type", "sha256"):
        _drop_column_if_exists("source_documents", col)

    # 新表
    for table in ("scoring_points", "extracted_facts", "document_chunks", "document_pages"):
        if _has_table(table):
            op.drop_table(table)
