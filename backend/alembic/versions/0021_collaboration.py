"""多人协作：项目成员、邀请、评论、待办、审核与通知。

- 新增 7 张协作表（project_members / project_invitations / project_comments /
  project_work_items / review_requests / review_decisions / notifications）。
- projects 增加 review_policy（默认 recommended，避免升级后阻断正式导出）与 revision 乐观锁列。
- extracted_facts / video_projects / video_segments 增加 revision 乐观锁列。
- 回填：所有现有项目 owner 自动成为 active 状态的 owner 成员。
- 不删除任何现有数据，不移除 projects.owner_id（保留唯一所有者语义）。
- SQLite 与 PostgreSQL 均可运行；列/表已存在时跳过（create_all 守卫）。
"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    # ---- 新增列（带 server_default，现有行自动回填）----
    _add_column_if_missing(
        "projects",
        sa.Column("review_policy", sa.String(16), nullable=False, server_default="recommended"),
    )
    _add_column_if_missing(
        "projects",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column_if_missing(
        "extracted_facts",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column_if_missing(
        "video_projects",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column_if_missing(
        "video_segments",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )

    # ---- project_members ----
    if not _has_table("project_members"):
        op.create_table(
            "project_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("invited_by", sa.String(36), nullable=True),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),
        )
        op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
        op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
        op.create_index("ix_project_members_status", "project_members", ["status"])
        op.create_index("ix_project_members_user", "project_members", ["user_id", "status"])

    # ---- 回填：现有项目 owner → active owner 成员（幂等）----
    bind = op.get_bind()
    projects = bind.execute(sa.text("SELECT id, owner_id, created_at FROM projects")).fetchall()
    for project_id, owner_id, created_at in projects:
        exists = bind.execute(
            sa.text("SELECT 1 FROM project_members WHERE project_id = :p AND user_id = :u"),
            {"p": project_id, "u": owner_id},
        ).fetchone()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO project_members "
                    "(id, project_id, user_id, role, status, invited_by, joined_at, created_at, updated_at) "
                    "VALUES (:id, :p, :u, 'owner', 'active', NULL, :t, :t, :t)"
                ),
                {"id": str(uuid4()), "p": project_id, "u": owner_id, "t": created_at},
            )

    # ---- project_invitations ----
    if not _has_table("project_invitations"):
        op.create_table(
            "project_invitations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("invited_by", sa.String(36), nullable=True),
            sa.Column("accepted_by", sa.String(36), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("token_hash", name="uq_project_invitations_token_hash"),
        )
        op.create_index("ix_project_invitations_project_id", "project_invitations", ["project_id"])
        op.create_index("ix_project_invitations_status", "project_invitations", ["status"])
        op.create_index("ix_project_invitations_token_hash", "project_invitations", ["token_hash"])
        op.create_index("ix_project_invitations_email", "project_invitations", ["project_id", "email", "status"])

    # ---- project_comments ----
    if not _has_table("project_comments"):
        op.create_table(
            "project_comments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_type", sa.String(32), nullable=False),
            sa.Column("target_id", sa.String(36), nullable=True),
            sa.Column("target_label", sa.String(255), nullable=True),
            sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_id", sa.String(36), sa.ForeignKey("project_comments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("resolved_by", sa.String(36), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_project_comments_project_id", "project_comments", ["project_id"])
        op.create_index("ix_project_comments_author_id", "project_comments", ["author_id"])
        op.create_index("ix_project_comments_status", "project_comments", ["status"])
        op.create_index(
            "ix_project_comments_target",
            "project_comments",
            ["project_id", "target_type", "target_id", "status"],
        )

    # ---- project_work_items ----
    if not _has_table("project_work_items"):
        op.create_table(
            "project_work_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("target_type", sa.String(32), nullable=True),
            sa.Column("target_id", sa.String(36), nullable=True),
            sa.Column("target_label", sa.String(255), nullable=True),
            sa.Column("assignee_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("comment_id", sa.String(36), nullable=True),
            sa.Column("priority", sa.String(16), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(16), nullable=False, server_default="todo"),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_project_work_items_project_id", "project_work_items", ["project_id"])
        op.create_index("ix_project_work_items_assignee_id", "project_work_items", ["assignee_id"])
        op.create_index("ix_project_work_items_status", "project_work_items", ["status"])
        op.create_index(
            "ix_project_work_items_assignee",
            "project_work_items",
            ["project_id", "assignee_id", "status"],
        )

    # ---- review_requests ----
    if not _has_table("review_requests"):
        op.create_table(
            "review_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_type", sa.String(32), nullable=False),
            sa.Column("target_id", sa.String(36), nullable=True),
            sa.Column("target_label", sa.String(255), nullable=True),
            sa.Column("target_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("snapshot_hash", sa.String(64), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("submitted_by", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assigned_reviewer_id", sa.String(36), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_review_requests_project_id", "review_requests", ["project_id"])
        op.create_index("ix_review_requests_submitted_by", "review_requests", ["submitted_by"])
        op.create_index("ix_review_requests_status", "review_requests", ["status"])
        op.create_index(
            "ix_review_requests_target",
            "review_requests",
            ["project_id", "target_type", "target_id", "status"],
        )

    # ---- review_decisions ----
    if not _has_table("review_decisions"):
        op.create_table(
            "review_decisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("review_request_id", sa.String(36), sa.ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("decision", sa.String(24), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("override_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_review_decisions_review_request_id", "review_decisions", ["review_request_id"])
        op.create_index("ix_review_decisions_reviewer_id", "review_decisions", ["reviewer_id"])

    # ---- notifications ----
    if not _has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("type", sa.String(48), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("link", sa.String(512), nullable=True),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_project_id", "notifications", ["project_id"])
        op.create_index("ix_notifications_type", "notifications", ["type"])
        op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read", "created_at"])


def downgrade() -> None:
    for table in (
        "notifications",
        "review_decisions",
        "review_requests",
        "project_work_items",
        "project_comments",
        "project_invitations",
    ):
        if _has_table(table):
            op.drop_table(table)
    # 成员回填不可安全逆转：仅删除非手工管理的 owner 回填行会破坏现有协作数据，
    # 因此 downgrade 保留 project_members 数据，仅删除表。
    if _has_table("project_members"):
        op.drop_table("project_members")
    for table, column in (
        ("video_segments", "revision"),
        ("video_projects", "revision"),
        ("extracted_facts", "revision"),
        ("projects", "revision"),
        ("projects", "review_policy"),
    ):
        if _has_column(table, column):
            op.drop_column(table, column)
