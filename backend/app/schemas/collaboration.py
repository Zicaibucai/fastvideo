"""协作相关 Schema：成员、邀请、评论、待办、审核、通知、审计。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedModel


# ---- 成员 ----
class MemberOut(TimestampedModel):
    project_id: str
    user_id: str
    role: str
    status: str
    invited_by: str | None
    joined_at: datetime
    # 关联用户信息（路由填充）
    username: str | None = None
    email: str | None = None
    full_name: str | None = None


class MemberRoleUpdate(BaseModel):
    role: str


class MemberRemoveRequest(BaseModel):
    reason: str | None = None


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: str
    reason: str | None = None


# ---- 邀请 ----
class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(pattern="^(bid_manager|technical_editor|media_editor|reviewer|viewer)$")


class InvitationOut(TimestampedModel):
    project_id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    invited_by: str | None
    accepted_by: str | None
    accepted_at: datetime | None


class InvitationCreatedOut(InvitationOut):
    """创建/重发邀请的响应：原始令牌与邀请链接仅此一次返回。"""

    invite_token: str
    invite_url: str


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=10)


class MyInvitationOut(InvitationOut):
    project_name: str | None = None
    inviter_name: str | None = None


# ---- 评论 ----
class CommentCreate(BaseModel):
    target_type: str
    target_id: str | None = None
    parent_id: str | None = None
    body: str = Field(min_length=1, max_length=4000)
    is_blocking: bool = False


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(TimestampedModel):
    project_id: str
    target_type: str
    target_id: str | None
    target_label: str | None
    author_id: str
    author_name: str | None = None
    parent_id: str | None
    body: str
    is_blocking: bool
    status: str
    resolved_by: str | None
    resolved_by_name: str | None = None
    resolved_at: datetime | None


# ---- 待办 ----
class WorkItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    assignee_id: str | None = None
    comment_id: str | None = None
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")
    due_at: datetime | None = None


class WorkItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    assignee_id: str | None = None
    priority: str | None = Field(default=None, pattern="^(low|medium|high|urgent)$")
    status: str | None = Field(
        default=None, pattern="^(todo|in_progress|blocked|done|cancelled)$"
    )
    due_at: datetime | None = None


class WorkItemOut(TimestampedModel):
    project_id: str
    title: str
    description: str | None
    target_type: str | None
    target_id: str | None
    target_label: str | None
    assignee_id: str | None
    assignee_name: str | None = None
    created_by: str | None
    created_by_name: str | None = None
    comment_id: str | None
    priority: str
    status: str
    due_at: datetime | None
    completed_at: datetime | None


# ---- 审核 ----
class ReviewSubmitRequest(BaseModel):
    target_type: str
    target_id: str | None = None
    note: str | None = None
    assigned_reviewer_id: str | None = None


class ReviewDecideRequest(BaseModel):
    decision: str = Field(pattern="^(approved|changes_requested|rejected)$")
    comment: str | None = None
    override_reason: str | None = None


class ReviewDecisionOut(TimestampedModel):
    review_request_id: str
    reviewer_id: str
    reviewer_name: str | None = None
    decision: str
    comment: str | None
    is_override: bool
    override_reason: str | None


class ReviewRequestOut(TimestampedModel):
    project_id: str
    target_type: str
    target_id: str | None
    target_label: str | None
    target_revision: int
    snapshot_hash: str
    note: str | None
    submitted_by: str
    submitted_by_name: str | None = None
    assigned_reviewer_id: str | None
    assigned_reviewer_name: str | None = None
    status: str
    submitted_at: datetime
    decided_at: datetime | None
    current_state: str | None = None  # 派生状态（approved_but_changed 等）
    decisions: list[ReviewDecisionOut] = []


class ReviewDetailOut(ReviewRequestOut):
    snapshot: dict | None = None
    current_snapshot: dict | None = None


class ReviewStatusOut(BaseModel):
    """项目关键目标的派生审核状态总览。"""

    review_policy: str
    facts: dict
    storyboard: dict
    video_project: dict | None = None


# ---- 通知 ----
class NotificationOut(TimestampedModel):
    project_id: str | None
    type: str
    title: str
    body: str | None
    link: str | None
    actor_id: str | None
    is_read: bool


# ---- 审计 ----
class AuditLogOut(TimestampedModel):
    user_id: str | None
    user_name: str | None
    project_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    detail: dict | None
    note: str | None


# ---- 权限说明 ----
class RolePermissionOut(BaseModel):
    role: str
    label: str
    permissions: list[str]
