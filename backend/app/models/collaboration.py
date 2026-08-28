"""多人协作模型：项目成员、邀请、评论、待办、审核与通知。

项目级 RBAC 独立于全局 User 模型：User 只表示平台账号（普通用户/超级管理员），
项目内角色由 ProjectMember.role 决定。所有协作对象都带 project_id，
便于校验目标对象归属并防止跨项目访问。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, utc_now

# ---- 项目角色 ----
PROJECT_ROLE_OWNER = "owner"
PROJECT_ROLE_BID_MANAGER = "bid_manager"
PROJECT_ROLE_TECHNICAL_EDITOR = "technical_editor"
PROJECT_ROLE_MEDIA_EDITOR = "media_editor"
PROJECT_ROLE_REVIEWER = "reviewer"
PROJECT_ROLE_VIEWER = "viewer"
PROJECT_ROLES = (
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_BID_MANAGER,
    PROJECT_ROLE_TECHNICAL_EDITOR,
    PROJECT_ROLE_MEDIA_EDITOR,
    PROJECT_ROLE_REVIEWER,
    PROJECT_ROLE_VIEWER,
)

# ---- 成员状态 ----
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_SUSPENDED = "suspended"
MEMBER_STATUS_LEFT = "left"
MEMBER_STATUSES = (MEMBER_STATUS_ACTIVE, MEMBER_STATUS_SUSPENDED, MEMBER_STATUS_LEFT)

# ---- 邀请状态 ----
INVITATION_STATUS_PENDING = "pending"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_REVOKED = "revoked"
INVITATION_STATUS_EXPIRED = "expired"

# ---- 评论状态 ----
COMMENT_STATUS_OPEN = "open"
COMMENT_STATUS_RESOLVED = "resolved"

# ---- 待办状态 ----
WORK_ITEM_STATUSES = ("todo", "in_progress", "blocked", "done", "cancelled")
WORK_ITEM_PRIORITIES = ("low", "medium", "high", "urgent")

# ---- 审核状态 ----
REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_CHANGES_REQUESTED = "changes_requested"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_CANCELLED = "cancelled"
REVIEW_STATUS_SUPERSEDED = "superseded"

REVIEW_DECISIONS = ("approved", "changes_requested", "rejected")

# 协作目标类型（评论 / 待办 / 审核共用一套校验）
TARGET_TYPE_PROJECT = "project"
TARGET_TYPE_FACTS = "facts"          # 工程信息整体（批量审核）
TARGET_TYPE_FACT = "fact"            # 单条工程参数
TARGET_TYPE_SCORING_POINT = "scoring_point"
TARGET_TYPE_STORYBOARD = "storyboard"  # 整份解说词文稿
TARGET_TYPE_SHOT = "shot"            # 单个分镜
TARGET_TYPE_RENDER_VERSION = "render_version"
TARGET_TYPE_VIDEO_GEN_VERSION = "video_gen_version"
TARGET_TYPE_AUDIO_VERSION = "audio_version"
TARGET_TYPE_VIDEO_PROJECT = "video_project"
TARGET_TYPE_VIDEO_SEGMENT = "video_segment"
TARGET_TYPE_EXPORT_TASK = "export_task"

# 可提交审核的目标类型
REVIEWABLE_TARGET_TYPES = (
    TARGET_TYPE_FACTS,
    TARGET_TYPE_FACT,
    TARGET_TYPE_STORYBOARD,
    TARGET_TYPE_SHOT,
    TARGET_TYPE_VIDEO_PROJECT,
)


class ProjectMember(BaseModel):
    """项目成员：项目级角色与状态。"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),
        Index("ix_project_members_user", "user_id", "status"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=PROJECT_ROLE_VIEWER)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MEMBER_STATUS_ACTIVE, index=True
    )
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    project = relationship("Project", back_populates="members")
    user = relationship("User")


class ProjectInvitation(BaseModel):
    """项目邀请：仅保存令牌哈希，原始令牌只在创建时返回一次。"""

    __tablename__ = "project_invitations"
    __table_args__ = (
        Index("ix_project_invitations_email", "project_id", "email", "status"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=PROJECT_ROLE_VIEWER)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=INVITATION_STATUS_PENDING, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")


class ProjectComment(BaseModel):
    """项目评论：可挂接到工程信息、评分点、分镜、画面/视频/配音版本、分段、导出任务等。

    业务对象删除策略：评论不级联删除（保留协作记录），
    通过 project_id 保证随项目整体删除。
    """

    __tablename__ = "project_comments"
    __table_args__ = (
        Index("ix_project_comments_target", "project_id", "target_type", "target_id", "status"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 显示定位
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_comments.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=COMMENT_STATUS_OPEN, index=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author = relationship("User")


class ProjectWorkItem(BaseModel):
    """项目待办：可分派给当前项目有效成员。"""

    __tablename__ = "project_work_items"
    __table_args__ = (
        Index("ix_project_work_items_assignee", "project_id", "assignee_id", "status"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    comment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 关联评论/审核意见
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="todo", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewRequest(BaseModel):
    """审核请求：绑定提交时的内容版本（revision + 快照哈希），而非只保存对象 ID。"""

    __tablename__ = "review_requests"
    __table_args__ = (
        Index("ix_review_requests_target", "project_id", "target_type", "target_id", "status"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 提交时内容快照
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=REVIEW_STATUS_PENDING, index=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decisions = relationship(
        "ReviewDecision", back_populates="review_request", cascade="all, delete-orphan"
    )


class ReviewDecision(BaseModel):
    """审核决定：批准 / 要求修改 / 驳回，必须附原因（批准可为空）。"""

    __tablename__ = "review_decisions"

    review_request_id: Mapped[str] = mapped_column(
        ForeignKey("review_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_request = relationship("ReviewRequest", back_populates="decisions")
    reviewer = relationship("User")


class Notification(BaseModel):
    """站内通知：邀请、待办、审核、评论提及、批准后变更等。"""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
