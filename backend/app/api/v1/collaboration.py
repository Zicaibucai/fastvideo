"""多人协作路由：成员、邀请、评论、待办、审核、审计、通知。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.audit_log import AuditLog
from app.models.base import utc_now
from app.models.collaboration import (
    COMMENT_STATUS_OPEN,
    COMMENT_STATUS_RESOLVED,
    INVITATION_STATUS_PENDING,
    MEMBER_STATUS_ACTIVE,
    PROJECT_ROLE_OWNER,
    REVIEW_STATUS_PENDING,
    Notification,
    ProjectComment,
    ProjectInvitation,
    ProjectMember,
    ProjectWorkItem,
    ReviewDecision,
    ReviewRequest,
    WORK_ITEM_STATUSES,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.collaboration import (
    AuditLogOut,
    CommentCreate,
    CommentOut,
    CommentUpdate,
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationCreatedOut,
    InvitationOut,
    MemberOut,
    MemberRemoveRequest,
    MemberRoleUpdate,
    MyInvitationOut,
    NotificationOut,
    ReviewDecideRequest,
    ReviewDecisionOut,
    ReviewDetailOut,
    ReviewRequestOut,
    ReviewStatusOut,
    ReviewSubmitRequest,
    RolePermissionOut,
    TransferOwnershipRequest,
    WorkItemCreate,
    WorkItemOut,
    WorkItemUpdate,
)
from app.schemas.common import Message
from app.services import collaboration_service as collab
from app.services import review_service
from app.services.audit import log_action
from app.services.notification_service import notify
from app.services.permissions import (
    PERM_AUDIT_VIEW,
    PERM_COMMENT_CREATE,
    PERM_COMMENT_RESOLVE,
    PERM_COMMENT_VIEW,
    PERM_MEMBER_MANAGE,
    PERM_MEMBER_VIEW,
    PERM_OWNERSHIP_TRANSFER,
    PERM_PROJECT_EDIT,
    PERM_REVIEW_DECIDE,
    PERM_REVIEW_SUBMIT,
    PERM_REVIEW_VIEW,
    PERM_TASK_ASSIGN,
    PERM_TASK_CREATE,
    PERM_TASK_UPDATE,
    PERM_TASK_VIEW,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    active_members,
    assert_active_member,
    get_member,
    get_project_access,
    permissions_for_role,
)
from app.services.target_resolver import COMMENTABLE_TARGET_TYPES, resolve_target

router = APIRouter(tags=["协作"])


# ============================================================
# 工具
# ============================================================

def _user_names(db: Session, user_ids: set[str]) -> dict[str, str]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    return {
        u.id: (u.full_name or u.username)
        for u in db.scalars(select(User).where(User.id.in_(ids))).all()
    }


def _member_out(db: Session, member: ProjectMember) -> MemberOut:
    user = db.get(User, member.user_id)
    out = MemberOut.model_validate(member)
    if user:
        out.username = user.username
        out.email = user.email
        out.full_name = user.full_name
    return out


def _comment_out(db: Session, comment: ProjectComment, names: dict[str, str] | None = None) -> CommentOut:
    names = names or _user_names(db, {comment.author_id, comment.resolved_by})
    out = CommentOut.model_validate(comment)
    out.author_name = names.get(comment.author_id)
    out.resolved_by_name = names.get(comment.resolved_by) if comment.resolved_by else None
    return out


def _work_item_out(db: Session, item: ProjectWorkItem, names: dict[str, str] | None = None) -> WorkItemOut:
    names = names or _user_names(db, {item.assignee_id, item.created_by})
    out = WorkItemOut.model_validate(item)
    out.assignee_name = names.get(item.assignee_id) if item.assignee_id else None
    out.created_by_name = names.get(item.created_by) if item.created_by else None
    return out


def _review_out(db: Session, request: ReviewRequest, names: dict[str, str] | None = None) -> ReviewRequestOut:
    decisions = list(request.decisions)
    ids = {request.submitted_by, request.assigned_reviewer_id} | {d.reviewer_id for d in decisions}
    names = names or _user_names(db, ids)
    out = ReviewRequestOut.model_validate(request)
    out.submitted_by_name = names.get(request.submitted_by)
    out.assigned_reviewer_name = names.get(request.assigned_reviewer_id) if request.assigned_reviewer_id else None
    out.decisions = []
    for d in decisions:
        d_out = ReviewDecisionOut.model_validate(d)
        d_out.reviewer_name = names.get(d.reviewer_id)
        out.decisions.append(d_out)
    if request.status == "approved":
        state = review_service.target_review_state(
            db, request.project_id, request.target_type, request.target_id
        )
        out.current_state = state["state"]
    else:
        out.current_state = request.status
    return out


def _extract_mentions(db: Session, project_id: str, body: str) -> list[str]:
    """从评论内容中提取 @用户名 / @姓名 提及的项目成员用户 ID。"""
    members = active_members(db, project_id)
    mentioned = []
    for member in members:
        user = db.get(User, member.user_id)
        if not user:
            continue
        for name in {user.username, user.full_name or ""}:
            if name and f"@{name}" in body:
                mentioned.append(user.id)
                break
    return mentioned


# ============================================================
# 角色与权限说明
# ============================================================

@router.get("/roles", response_model=list[RolePermissionOut], summary="项目角色与权限说明")
def list_role_permissions(current: User = Depends(get_current_user)) -> list[RolePermissionOut]:
    return [
        RolePermissionOut(role=role, label=ROLE_LABELS.get(role, role), permissions=sorted(perms))
        for role, perms in ROLE_PERMISSIONS.items()
    ]


# ============================================================
# 成员管理
# ============================================================

@router.get("/projects/{project_id}/members", response_model=list[MemberOut], summary="项目成员列表")
def list_members(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[MemberOut]:
    get_project_access(db, project_id, current, PERM_MEMBER_VIEW)
    members = list(
        db.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.joined_at.asc())
        ).all()
    )
    return [_member_out(db, m) for m in members]


@router.patch("/projects/{project_id}/members/{member_id}", response_model=MemberOut, summary="修改成员角色")
def update_member_role(
    project_id: str,
    member_id: str,
    payload: MemberRoleUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> MemberOut:
    access = get_project_access(db, project_id, current, PERM_MEMBER_MANAGE)
    member = db.get(ProjectMember, member_id)
    if not member or member.project_id != project_id:
        raise NotFoundError("成员不存在")
    collab.change_member_role(db, access=access, member=member, new_role=payload.role)
    db.commit()
    db.refresh(member)
    return _member_out(db, member)


@router.delete("/projects/{project_id}/members/{member_id}", response_model=Message, summary="移除成员")
def remove_member(
    project_id: str,
    member_id: str,
    payload: MemberRemoveRequest | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Message:
    access = get_project_access(db, project_id, current, PERM_MEMBER_MANAGE)
    member = db.get(ProjectMember, member_id)
    if not member or member.project_id != project_id:
        raise NotFoundError("成员不存在")
    collab.remove_member(db, access=access, member=member, reason=payload.reason if payload else None)
    db.commit()
    return Message(message="成员已移除")


@router.post("/projects/{project_id}/members/leave", response_model=Message, summary="退出项目")
def leave_project(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Message:
    access = get_project_access(db, project_id, current)
    collab.leave_project(db, user=current, project=access.project)
    db.commit()
    return Message(message="已退出项目")


@router.post("/projects/{project_id}/transfer-ownership", response_model=Message, summary="转移项目所有权")
def transfer_ownership(
    project_id: str,
    payload: TransferOwnershipRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Message:
    access = get_project_access(db, project_id, current, PERM_OWNERSHIP_TRANSFER)
    collab.transfer_ownership(
        db, access=access, new_owner_user_id=payload.new_owner_user_id, reason=payload.reason
    )
    db.commit()
    return Message(message="项目所有权已转移")


# ============================================================
# 邀请
# ============================================================

def _invitation_created_out(invitation: ProjectInvitation, token: str) -> InvitationCreatedOut:
    return InvitationCreatedOut(
        **InvitationOut.model_validate(invitation).model_dump(),
        invite_token=token,
        invite_url=f"/invite/accept?token={token}",
    )


@router.get("/projects/{project_id}/invitations", response_model=list[InvitationOut], summary="邀请列表")
def list_invitations(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[InvitationOut]:
    get_project_access(db, project_id, current, PERM_MEMBER_MANAGE)
    return list(
        db.scalars(
            select(ProjectInvitation)
            .where(ProjectInvitation.project_id == project_id)
            .order_by(ProjectInvitation.created_at.desc())
        ).all()
    )


@router.post(
    "/projects/{project_id}/invitations",
    response_model=InvitationCreatedOut,
    status_code=201,
    summary="邀请成员（重复邀请同邮箱视为重发）",
)
def create_invitation(
    project_id: str,
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> InvitationCreatedOut:
    access = get_project_access(db, project_id, current, PERM_MEMBER_MANAGE)
    invitation, token = collab.create_invitation(
        db, access=access, email=payload.email, role=payload.role
    )
    db.commit()
    db.refresh(invitation)
    return _invitation_created_out(invitation, token)


@router.post(
    "/projects/{project_id}/invitations/{invitation_id}/resend",
    response_model=InvitationCreatedOut,
    summary="重新发送邀请（吊销旧令牌）",
)
def resend_invitation(
    project_id: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> InvitationCreatedOut:
    access = get_project_access(db, project_id, current, PERM_MEMBER_MANAGE)
    invitation = db.get(ProjectInvitation, invitation_id)
    if not invitation or invitation.project_id != project_id:
        raise NotFoundError("邀请不存在")
    if invitation.status != INVITATION_STATUS_PENDING:
        raise ConflictError("只有待接受的邀请可以重发")
    new_invitation, token = collab.create_invitation(
        db, access=access, email=invitation.email, role=invitation.role
    )
    db.commit()
    db.refresh(new_invitation)
    return _invitation_created_out(new_invitation, token)


@router.post("/projects/{project_id}/invitations/{invitation_id}/revoke", response_model=InvitationOut, summary="撤销邀请")
def revoke_invitation(
    project_id: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> InvitationOut:
    access = get_project_access(db, project_id, current, PERM_MEMBER_MANAGE)
    invitation = db.get(ProjectInvitation, invitation_id)
    if not invitation or invitation.project_id != project_id:
        raise NotFoundError("邀请不存在")
    if invitation.status != INVITATION_STATUS_PENDING:
        raise ConflictError("只有待接受的邀请可以撤销")
    invitation.status = "revoked"
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="invitation_revoke",
        entity_type="project_invitation",
        entity_id=invitation.id,
        detail={"email": invitation.email},
        commit=False,
    )
    db.commit()
    db.refresh(invitation)
    return InvitationOut.model_validate(invitation)


@router.get("/invitations/mine", response_model=list[MyInvitationOut], summary="我收到的待处理邀请")
def my_invitations(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[MyInvitationOut]:
    invitations = list(
        db.scalars(
            select(ProjectInvitation).where(
                func.lower(ProjectInvitation.email) == current.email.strip().lower(),
                ProjectInvitation.status == INVITATION_STATUS_PENDING,
            )
        ).all()
    )
    result = []
    for inv in invitations:
        if collab.is_expired(inv.expires_at):
            inv.status = "expired"
            db.flush()
            continue
        out = MyInvitationOut.model_validate(inv)
        project = db.get(Project, inv.project_id)
        inviter = db.get(User, inv.invited_by) if inv.invited_by else None
        out.project_name = project.name if project else None
        out.inviter_name = inviter.username if inviter else None
        result.append(out)
    db.commit()
    return result


@router.post("/invitations/accept", response_model=MemberOut, summary="接受邀请")
def accept_invitation(
    payload: InvitationAcceptRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> MemberOut:
    invitation = collab.accept_invitation(db, token=payload.token, user=current)
    db.commit()
    member = get_member(db, invitation.project_id, current.id)
    return _member_out(db, member)


# ============================================================
# 评论
# ============================================================

@router.get("/projects/{project_id}/comments", response_model=list[CommentOut], summary="评论列表")
def list_comments(
    project_id: str,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[CommentOut]:
    get_project_access(db, project_id, current, PERM_COMMENT_VIEW)
    stmt = select(ProjectComment).where(ProjectComment.project_id == project_id)
    if target_type:
        stmt = stmt.where(ProjectComment.target_type == target_type)
    if target_id:
        stmt = stmt.where(ProjectComment.target_id == target_id)
    if status:
        stmt = stmt.where(ProjectComment.status == status)
    comments = list(db.scalars(stmt.order_by(ProjectComment.created_at.asc())).all())
    names = _user_names(db, {c.author_id for c in comments} | {c.resolved_by for c in comments})
    return [_comment_out(db, c, names) for c in comments]


@router.post("/projects/{project_id}/comments", response_model=CommentOut, status_code=201, summary="发表评论")
def create_comment(
    project_id: str,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> CommentOut:
    access = get_project_access(db, project_id, current, PERM_COMMENT_CREATE)
    if payload.target_type not in COMMENTABLE_TARGET_TYPES:
        raise ConflictError(f"不支持的评论目标类型：{payload.target_type}")
    _, label = resolve_target(db, project_id, payload.target_type, payload.target_id)
    if payload.parent_id:
        parent = db.get(ProjectComment, payload.parent_id)
        if not parent or parent.project_id != project_id:
            raise NotFoundError("回复的评论不存在或不属于当前项目")
        # 回复必须挂在同一目标下
        if parent.target_type != payload.target_type or parent.target_id != payload.target_id:
            raise ConflictError("回复必须与原评论挂在同一对象下")

    comment = ProjectComment(
        project_id=project_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_label=label,
        author_id=current.id,
        parent_id=payload.parent_id,
        body=payload.body,
        is_blocking=payload.is_blocking,
        status=COMMENT_STATUS_OPEN,
    )
    db.add(comment)
    db.flush()

    # 提及通知
    for uid in _extract_mentions(db, project_id, payload.body):
        notify(
            db,
            user_id=uid,
            type="comment_mentioned",
            title=f"{current.username} 在评论中提到了你",
            body=payload.body[:200],
            project_id=project_id,
            link=f"/project/{project_id}/collaboration?tab=comments",
            actor=current,
        )
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="comment_create",
        entity_type=payload.target_type,
        entity_id=payload.target_id,
        detail={"comment_id": comment.id, "is_blocking": payload.is_blocking},
        commit=False,
    )
    db.commit()
    db.refresh(comment)
    return _comment_out(db, comment)


def _get_comment(db: Session, project_id: str, comment_id: str) -> ProjectComment:
    comment = db.get(ProjectComment, comment_id)
    if not comment or comment.project_id != project_id:
        raise NotFoundError("评论不存在")
    return comment


@router.patch("/projects/{project_id}/comments/{comment_id}", response_model=CommentOut, summary="编辑评论（仅作者）")
def update_comment(
    project_id: str,
    comment_id: str,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> CommentOut:
    get_project_access(db, project_id, current, PERM_COMMENT_VIEW)
    comment = _get_comment(db, project_id, comment_id)
    if comment.author_id != current.id:
        raise ForbiddenError("只有评论作者可以编辑评论")
    comment.body = payload.body
    db.commit()
    db.refresh(comment)
    return _comment_out(db, comment)


@router.post("/projects/{project_id}/comments/{comment_id}/resolve", response_model=CommentOut, summary="解决评论")
def resolve_comment(
    project_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> CommentOut:
    access = get_project_access(db, project_id, current, PERM_COMMENT_VIEW)
    comment = _get_comment(db, project_id, comment_id)
    if comment.author_id != current.id:
        access.require(PERM_COMMENT_RESOLVE)
    comment.status = COMMENT_STATUS_RESOLVED
    comment.resolved_by = current.id
    comment.resolved_at = utc_now()
    notify(
        db,
        user_id=comment.author_id,
        type="comment_resolved",
        title=f"你的评论已被解决：{comment.target_label or comment.target_type}",
        project_id=project_id,
        link=f"/project/{project_id}/collaboration?tab=comments",
        actor=current,
    )
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="comment_resolve",
        entity_type=comment.target_type,
        entity_id=comment.target_id,
        detail={"comment_id": comment.id},
        commit=False,
    )
    db.commit()
    db.refresh(comment)
    return _comment_out(db, comment)


@router.post("/projects/{project_id}/comments/{comment_id}/reopen", response_model=CommentOut, summary="重新打开评论")
def reopen_comment(
    project_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> CommentOut:
    access = get_project_access(db, project_id, current, PERM_COMMENT_VIEW)
    comment = _get_comment(db, project_id, comment_id)
    if comment.author_id != current.id:
        access.require(PERM_COMMENT_RESOLVE)
    comment.status = COMMENT_STATUS_OPEN
    comment.resolved_by = None
    comment.resolved_at = None
    db.commit()
    db.refresh(comment)
    return _comment_out(db, comment)


@router.delete("/projects/{project_id}/comments/{comment_id}", status_code=204, summary="删除评论")
def delete_comment(
    project_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    access = get_project_access(db, project_id, current, PERM_COMMENT_VIEW)
    comment = _get_comment(db, project_id, comment_id)
    if comment.author_id != current.id:
        access.require(PERM_PROJECT_EDIT)  # owner / bid_manager 可删除他人评论
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="comment_delete",
        entity_type=comment.target_type,
        entity_id=comment.target_id,
        detail={"comment_id": comment.id},
        commit=False,
    )
    db.delete(comment)
    db.commit()


# ============================================================
# 待办
# ============================================================

@router.get("/projects/{project_id}/work-items", response_model=list[WorkItemOut], summary="待办列表")
def list_work_items(
    project_id: str,
    assignee_id: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    due_before: datetime | None = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[WorkItemOut]:
    get_project_access(db, project_id, current, PERM_TASK_VIEW)
    stmt = select(ProjectWorkItem).where(ProjectWorkItem.project_id == project_id)
    if mine:
        stmt = stmt.where(ProjectWorkItem.assignee_id == current.id)
    elif assignee_id:
        stmt = stmt.where(ProjectWorkItem.assignee_id == assignee_id)
    if status:
        stmt = stmt.where(ProjectWorkItem.status == status)
    if priority:
        stmt = stmt.where(ProjectWorkItem.priority == priority)
    if due_before:
        stmt = stmt.where(ProjectWorkItem.due_at <= due_before)
    items = list(
        db.scalars(stmt.order_by(ProjectWorkItem.due_at.asc().nulls_last(), ProjectWorkItem.created_at.desc())).all()
    )
    names = _user_names(db, {i.assignee_id for i in items} | {i.created_by for i in items})
    return [_work_item_out(db, i, names) for i in items]


@router.post("/projects/{project_id}/work-items", response_model=WorkItemOut, status_code=201, summary="创建待办")
def create_work_item(
    project_id: str,
    payload: WorkItemCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> WorkItemOut:
    access = get_project_access(db, project_id, current, PERM_TASK_CREATE)
    label = None
    if payload.target_type:
        _, label = resolve_target(db, project_id, payload.target_type, payload.target_id)
    if payload.comment_id:
        comment = db.get(ProjectComment, payload.comment_id)
        if not comment or comment.project_id != project_id:
            raise NotFoundError("关联的评论不存在或不属于当前项目")
    assignee_id = payload.assignee_id
    if assignee_id:
        if assignee_id != current.id:
            access.require(PERM_TASK_ASSIGN)
        assert_active_member(db, project_id, assignee_id)

    item = ProjectWorkItem(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_label=label,
        assignee_id=assignee_id,
        created_by=current.id,
        comment_id=payload.comment_id,
        priority=payload.priority,
        status="todo",
        due_at=payload.due_at,
    )
    db.add(item)
    db.flush()
    if assignee_id:
        notify(
            db,
            user_id=assignee_id,
            type="task_assigned",
            title=f"新待办：{item.title}",
            body=payload.description,
            project_id=project_id,
            link=f"/project/{project_id}/collaboration?tab=tasks",
            actor=current,
        )
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="task_create",
        entity_type=payload.target_type,
        entity_id=payload.target_id,
        detail={"work_item_id": item.id, "assignee_id": assignee_id, "priority": item.priority},
        commit=False,
    )
    db.commit()
    db.refresh(item)
    return _work_item_out(db, item)


@router.patch("/projects/{project_id}/work-items/{item_id}", response_model=WorkItemOut, summary="更新待办")
def update_work_item(
    project_id: str,
    item_id: str,
    payload: WorkItemUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> WorkItemOut:
    access = get_project_access(db, project_id, current, PERM_TASK_VIEW)
    item = db.get(ProjectWorkItem, item_id)
    if not item or item.project_id != project_id:
        raise NotFoundError("待办不存在")

    data = payload.model_dump(exclude_unset=True)
    is_assignee = item.assignee_id == current.id
    is_creator = item.created_by == current.id

    # 状态变化：负责人、创建者或具备 task.update 权限的成员
    if "status" in data:
        new_status = data["status"]
        if new_status not in WORK_ITEM_STATUSES:
            raise ConflictError(f"无效的待办状态：{new_status}")
        if not (is_assignee or is_creator):
            access.require(PERM_TASK_UPDATE)
        old_status = item.status
        item.status = new_status
        item.completed_at = utc_now() if new_status == "done" else None
        if new_status != old_status:
            for uid in {item.assignee_id, item.created_by}:
                notify(
                    db,
                    user_id=uid,
                    type="task_status_changed",
                    title=f"待办「{item.title}」状态：{old_status} → {new_status}",
                    project_id=project_id,
                    link=f"/project/{project_id}/collaboration?tab=tasks",
                    actor=current,
                )
            log_action(
                db,
                user=current,
                project_id=project_id,
                action="task_status_change",
                entity_type=item.target_type,
                entity_id=item.target_id,
                detail={"work_item_id": item.id, "old_status": old_status, "new_status": new_status},
                commit=False,
            )
        data.pop("status")

    # 重新分派：需要 task.assign，且只能分派给有效成员
    if "assignee_id" in data:
        new_assignee = data.pop("assignee_id")
        if new_assignee != item.assignee_id:
            access.require(PERM_TASK_ASSIGN)
            if new_assignee:
                assert_active_member(db, project_id, new_assignee)
            item.assignee_id = new_assignee
            notify(
                db,
                user_id=new_assignee,
                type="task_assigned",
                title=f"待办分派给你：{item.title}",
                project_id=project_id,
                link=f"/project/{project_id}/collaboration?tab=tasks",
                actor=current,
            )

    # 其他字段：创建者或 task.update
    if data:
        if not is_creator:
            access.require(PERM_TASK_UPDATE)
        for field, value in data.items():
            setattr(item, field, value)

    db.commit()
    db.refresh(item)
    return _work_item_out(db, item)


@router.delete("/projects/{project_id}/work-items/{item_id}", status_code=204, summary="删除待办")
def delete_work_item(
    project_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    access = get_project_access(db, project_id, current, PERM_TASK_VIEW)
    item = db.get(ProjectWorkItem, item_id)
    if not item or item.project_id != project_id:
        raise NotFoundError("待办不存在")
    if item.created_by != current.id:
        access.require(PERM_TASK_ASSIGN)
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="task_delete",
        entity_type=item.target_type,
        entity_id=item.target_id,
        detail={"work_item_id": item.id, "title": item.title},
        commit=False,
    )
    db.delete(item)
    db.commit()


# ============================================================
# 审核
# ============================================================

@router.get("/projects/{project_id}/review-status", response_model=ReviewStatusOut, summary="项目审核状态总览")
def review_status(
    project_id: str,
    video_project_id: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ReviewStatusOut:
    access = get_project_access(db, project_id, current, PERM_REVIEW_VIEW)
    facts = review_service.target_review_state(db, project_id, "facts")
    storyboard = review_service.target_review_state(db, project_id, "storyboard")
    vp_state = None
    if video_project_id:
        vp_state = review_service.target_review_state(db, project_id, "video_project", video_project_id)

    def _brief(state: dict) -> dict:
        request = state.get("request")
        return {
            "state": state["state"],
            "changed_after_approval": state.get("changed_after_approval", False),
            "request_id": request.id if request else None,
            "submitted_by": request.submitted_by if request else None,
            "submitted_at": request.submitted_at.isoformat() if request else None,
        }

    return ReviewStatusOut(
        review_policy=access.project.review_policy or "recommended",
        facts=_brief(facts),
        storyboard=_brief(storyboard),
        video_project=_brief(vp_state) if vp_state else None,
    )


@router.get("/projects/{project_id}/reviews", response_model=list[ReviewRequestOut], summary="审核请求列表")
def list_reviews(
    project_id: str,
    status: str | None = None,
    target_type: str | None = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ReviewRequestOut]:
    get_project_access(db, project_id, current, PERM_REVIEW_VIEW)
    stmt = select(ReviewRequest).where(ReviewRequest.project_id == project_id)
    if status:
        stmt = stmt.where(ReviewRequest.status == status)
    if target_type:
        stmt = stmt.where(ReviewRequest.target_type == target_type)
    if mine:
        stmt = stmt.where(ReviewRequest.submitted_by == current.id)
    requests = list(db.scalars(stmt.order_by(ReviewRequest.submitted_at.desc())).all())
    return [_review_out(db, r) for r in requests]


@router.post("/projects/{project_id}/reviews", response_model=ReviewRequestOut, status_code=201, summary="提交审核")
def submit_review(
    project_id: str,
    payload: ReviewSubmitRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ReviewRequestOut:
    access = get_project_access(db, project_id, current, PERM_REVIEW_SUBMIT)
    request = review_service.submit_review(
        db,
        access=access,
        target_type=payload.target_type,
        target_id=payload.target_id,
        note=payload.note,
        assigned_reviewer_id=payload.assigned_reviewer_id,
    )
    db.commit()
    db.refresh(request)
    return _review_out(db, request)


@router.get("/projects/{project_id}/reviews/{request_id}", response_model=ReviewDetailOut, summary="审核详情（含快照与当前内容）")
def review_detail(
    project_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ReviewDetailOut:
    get_project_access(db, project_id, current, PERM_REVIEW_VIEW)
    request = db.get(ReviewRequest, request_id)
    if not request or request.project_id != project_id:
        raise NotFoundError("审核请求不存在")
    out = ReviewDetailOut(**_review_out(db, request).model_dump())
    out.snapshot = request.snapshot
    try:
        _, _, current_snapshot, _ = review_service.compute_snapshot(
            db, project_id, request.target_type, request.target_id
        )
        out.current_snapshot = current_snapshot
    except NotFoundError:
        out.current_snapshot = None
    return out


@router.post("/projects/{project_id}/reviews/{request_id}/decide", response_model=ReviewRequestOut, summary="审核决定")
def decide_review(
    project_id: str,
    request_id: str,
    payload: ReviewDecideRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ReviewRequestOut:
    access = get_project_access(db, project_id, current, PERM_REVIEW_VIEW)
    request = db.get(ReviewRequest, request_id)
    if not request or request.project_id != project_id:
        raise NotFoundError("审核请求不存在")
    is_self = request.submitted_by == current.id
    if is_self:
        from app.services.permissions import PERM_ADMIN_OVERRIDE

        access.require(PERM_ADMIN_OVERRIDE)  # 自审必须走管理覆盖
    else:
        access.require(PERM_REVIEW_DECIDE)
    review_service.decide_review(
        db,
        access=access,
        request=request,
        decision=payload.decision,
        comment=payload.comment,
        override_reason=payload.override_reason,
    )
    db.commit()
    db.refresh(request)
    return _review_out(db, request)


@router.post("/projects/{project_id}/reviews/{request_id}/cancel", response_model=ReviewRequestOut, summary="撤销审核请求")
def cancel_review(
    project_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ReviewRequestOut:
    access = get_project_access(db, project_id, current, PERM_REVIEW_VIEW)
    request = db.get(ReviewRequest, request_id)
    if not request or request.project_id != project_id:
        raise NotFoundError("审核请求不存在")
    if request.status != REVIEW_STATUS_PENDING:
        raise ConflictError("只有待审核的请求可以撤销")
    if request.submitted_by != current.id:
        access.require(PERM_PROJECT_EDIT)
    request.status = "cancelled"
    log_action(
        db,
        user=current,
        project_id=project_id,
        action="review_cancel",
        entity_type=request.target_type,
        entity_id=request.target_id,
        detail={"request_id": request.id},
        commit=False,
    )
    db.commit()
    db.refresh(request)
    return _review_out(db, request)


# ============================================================
# 协作动态与审计
# ============================================================

@router.get("/projects/{project_id}/audit-logs", response_model=list[AuditLogOut], summary="项目审计记录")
def list_audit_logs(
    project_id: str,
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[AuditLogOut]:
    get_project_access(db, project_id, current, PERM_AUDIT_VIEW)
    stmt = select(AuditLog).where(AuditLog.project_id == project_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list(
        db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    )


@router.get("/projects/{project_id}/collaboration/summary", summary="协作中心总览")
def collaboration_summary(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    access = get_project_access(db, project_id, current, PERM_TASK_VIEW)
    open_comments = db.scalar(
        select(func.count(ProjectComment.id)).where(
            ProjectComment.project_id == project_id,
            ProjectComment.status == COMMENT_STATUS_OPEN,
        )
    ) or 0
    open_tasks = db.scalar(
        select(func.count(ProjectWorkItem.id)).where(
            ProjectWorkItem.project_id == project_id,
            ProjectWorkItem.status.in_(["todo", "in_progress", "blocked"]),
        )
    ) or 0
    my_tasks = db.scalar(
        select(func.count(ProjectWorkItem.id)).where(
            ProjectWorkItem.project_id == project_id,
            ProjectWorkItem.assignee_id == current.id,
            ProjectWorkItem.status.in_(["todo", "in_progress", "blocked"]),
        )
    ) or 0
    pending_reviews = db.scalar(
        select(func.count(ReviewRequest.id)).where(
            ReviewRequest.project_id == project_id,
            ReviewRequest.status == REVIEW_STATUS_PENDING,
        )
    ) or 0
    member_count = db.scalar(
        select(func.count(ProjectMember.id)).where(
            ProjectMember.project_id == project_id,
            ProjectMember.status == MEMBER_STATUS_ACTIVE,
        )
    ) or 0
    recent_logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.project_id == project_id)
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        ).all()
    )
    return {
        "open_comment_count": open_comments,
        "open_task_count": open_tasks,
        "my_open_task_count": my_tasks,
        "pending_review_count": pending_reviews,
        "member_count": member_count,
        "my_role": access.role,
        "my_permissions": sorted(access.permissions),
        "review_policy": access.project.review_policy,
        "recent_activity": [
            {
                "id": log.id,
                "action": log.action,
                "user_name": log.user_name,
                "entity_type": log.entity_type,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in recent_logs
        ],
    }


# ============================================================
# 通知中心
# ============================================================

@router.get("/notifications", response_model=list[NotificationOut], summary="通知列表")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[NotificationOut]:
    stmt = select(Notification).where(Notification.user_id == current.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(db.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit)).all())


@router.get("/notifications/unread-count", summary="未读通知数")
def unread_count(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current.id,
            Notification.is_read.is_(False),
        )
    ) or 0
    return {"count": count}


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut, summary="标记已读")
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> NotificationOut:
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != current.id:
        raise NotFoundError("通知不存在")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return NotificationOut.model_validate(notification)


@router.post("/notifications/read-all", response_model=Message, summary="全部标记已读")
def mark_all_read(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Message:
    items = db.scalars(
        select(Notification).where(
            Notification.user_id == current.id,
            Notification.is_read.is_(False),
        )
    ).all()
    for item in items:
        item.is_read = True
    db.commit()
    return Message(message=f"已标记 {len(items)} 条通知为已读")
