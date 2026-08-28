"""项目成员与邀请服务。

邀请令牌规则：
- 原始令牌只在创建/重发时返回一次；
- 数据库只保存 SHA-256 哈希；
- 令牌 7 天过期、单次使用；
- 只能由对应邮箱的已登录账号接受；
- 撤销/过期/已接受的邀请不可再使用。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.base import utc_now
from app.models.collaboration import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_EXPIRED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_LEFT,
    MEMBER_STATUS_SUSPENDED,
    PROJECT_ROLE_BID_MANAGER,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLES,
    ProjectInvitation,
    ProjectMember,
)
from app.models.project import Project
from app.models.user import User
from app.services.audit import log_action
from app.services.notification_service import notify
from app.services.permissions import get_member

INVITATION_TTL_DAYS = 7


def is_expired(expires_at) -> bool:
    # SQLite 返回无时区时间，PostgreSQL 返回带时区时间，统一按 UTC 比较
    now = utc_now()
    if expires_at.tzinfo is None:
        return expires_at <= now.replace(tzinfo=None)
    return expires_at <= now


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _count_active_owners(db: Session, project_id: str) -> int:
    return db.scalar(
        select(func.count(ProjectMember.id)).where(
            ProjectMember.project_id == project_id,
            ProjectMember.role == PROJECT_ROLE_OWNER,
            ProjectMember.status == MEMBER_STATUS_ACTIVE,
        )
    ) or 0


def assert_not_last_owner(db: Session, member: ProjectMember, action: str) -> None:
    """项目必须始终至少存在一个 active owner。"""
    if member.role == PROJECT_ROLE_OWNER and member.status == MEMBER_STATUS_ACTIVE:
        if _count_active_owners(db, member.project_id) <= 1:
            raise ConflictError(f"项目是后一个所有者不能{action}，请先转移项目所有权")


def create_invitation(
    db: Session,
    *,
    access,
    email: str,
    role: str,
) -> tuple[ProjectInvitation, str]:
    """创建邀请。返回 (邀请记录, 原始令牌) —— 原始令牌仅此一次返回。"""
    project = access.project
    email = normalize_email(email)
    if not email or "@" not in email:
        raise ConflictError("邀请邮箱格式无效")
    if role not in PROJECT_ROLES:
        raise ConflictError(f"无效的项目角色：{role}")
    if role == PROJECT_ROLE_OWNER:
        raise ConflictError("邀请不能直接授予所有者角色，请使用所有权转移")

    # 已是有效成员
    existing_user = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing_user:
        member = get_member(db, project.id, existing_user.id)
        if member and member.status == MEMBER_STATUS_ACTIVE:
            raise ConflictError("该用户已是项目成员")

    # 同邮箱存在 pending 邀请 → 视为重发：吊销旧的，签发新令牌
    pending = list(
        db.scalars(
            select(ProjectInvitation).where(
                ProjectInvitation.project_id == project.id,
                func.lower(ProjectInvitation.email) == email,
                ProjectInvitation.status == INVITATION_STATUS_PENDING,
            )
        ).all()
    )
    for old in pending:
        old.status = INVITATION_STATUS_REVOKED

    token = secrets.token_urlsafe(32)
    invitation = ProjectInvitation(
        project_id=project.id,
        email=email,
        role=role,
        token_hash=hash_invite_token(token),
        status=INVITATION_STATUS_PENDING,
        expires_at=utc_now() + timedelta(days=INVITATION_TTL_DAYS),
        invited_by=access.user.id,
    )
    db.add(invitation)
    db.flush()

    # 被邀请人已有账号时发站内通知
    if existing_user:
        notify(
            db,
            user_id=existing_user.id,
            type="project_invited",
            title=f"你被邀请加入项目「{project.name}」",
            body=f"角色：{role}。请在协作中心或通知中接受邀请。",
            project_id=project.id,
            link="/invitations",
            actor=access.user,
        )

    log_action(
        db,
        user=access.user,
        project_id=project.id,
        action="member_invite",
        entity_type="project_invitation",
        entity_id=invitation.id,
        detail={"email": email, "role": role, "resent": bool(pending)},
        commit=False,
    )
    return invitation, token


def accept_invitation(db: Session, *, token: str, user: User) -> ProjectInvitation:
    """接受邀请：校验令牌、有效期、状态与登录邮箱。"""
    if not user.is_active:
        raise ForbiddenError("账号已停用，不能接受邀请")
    invitation = db.scalar(
        select(ProjectInvitation).where(
            ProjectInvitation.token_hash == hash_invite_token(token)
        )
    )
    if invitation is None:
        raise NotFoundError("邀请不存在或链接无效")
    if invitation.status == INVITATION_STATUS_PENDING and is_expired(invitation.expires_at):
        invitation.status = INVITATION_STATUS_EXPIRED
        db.commit()  # 过期状态独立于本次请求提交，避免随 409 回滚
    if invitation.status != INVITATION_STATUS_PENDING:
        raise ConflictError("邀请已使用、已撤销或已过期")
    if normalize_email(user.email) != normalize_email(invitation.email):
        raise ForbiddenError("该邀请只能由对应邮箱的账号接受")

    member = get_member(db, invitation.project_id, user.id)
    if member is None:
        member = ProjectMember(
            project_id=invitation.project_id,
            user_id=user.id,
            role=invitation.role,
            status=MEMBER_STATUS_ACTIVE,
            invited_by=invitation.invited_by,
        )
        db.add(member)
    else:
        member.role = invitation.role
        member.status = MEMBER_STATUS_ACTIVE
        member.invited_by = invitation.invited_by

    now = utc_now()
    invitation.status = INVITATION_STATUS_ACCEPTED
    invitation.accepted_by = user.id
    invitation.accepted_at = now
    member.joined_at = now
    db.flush()

    project = db.get(Project, invitation.project_id)
    notify(
        db,
        user_id=invitation.invited_by,
        type="invitation_accepted",
        title=f"{user.username} 已接受项目「{project.name if project else ''}」的邀请",
        project_id=invitation.project_id,
        link=f"/project/{invitation.project_id}/collaboration?tab=members",
        actor=user,
    )
    log_action(
        db,
        user=user,
        project_id=invitation.project_id,
        action="member_join",
        entity_type="project_member",
        entity_id=member.id,
        detail={"role": invitation.role, "via": "invitation"},
        commit=False,
    )
    return invitation


def change_member_role(
    db: Session, *, access, member: ProjectMember, new_role: str
) -> ProjectMember:
    if new_role not in PROJECT_ROLES:
        raise ConflictError(f"无效的项目角色：{new_role}")
    if new_role == PROJECT_ROLE_OWNER:
        raise ConflictError("请使用所有权转移来变更所有者")
    if member.role == PROJECT_ROLE_OWNER:
        assert_not_last_owner(db, member, "被降级")
    old_role = member.role
    member.role = new_role
    db.flush()
    log_action(
        db,
        user=access.user,
        project_id=member.project_id,
        action="member_role_change",
        entity_type="project_member",
        entity_id=member.id,
        detail={"user_id": member.user_id, "old_role": old_role, "new_role": new_role},
        commit=False,
    )
    return member


def remove_member(db: Session, *, access, member: ProjectMember, reason: str | None = None) -> None:
    assert_not_last_owner(db, member, "被移除")
    member.status = MEMBER_STATUS_LEFT
    db.flush()
    notify(
        db,
        user_id=member.user_id,
        type="member_removed",
        title=f"你已被移出项目「{access.project.name}」",
        project_id=member.project_id,
        actor=access.user,
    )
    log_action(
        db,
        user=access.user,
        project_id=member.project_id,
        action="member_remove",
        entity_type="project_member",
        entity_id=member.id,
        detail={"user_id": member.user_id, "reason": reason},
        commit=False,
    )


def leave_project(db: Session, *, user: User, project: Project) -> None:
    member = get_member(db, project.id, user.id)
    if member is None or member.status != MEMBER_STATUS_ACTIVE:
        raise NotFoundError("你不是该项目成员")
    assert_not_last_owner(db, member, "退出")
    member.status = MEMBER_STATUS_LEFT
    db.flush()
    log_action(
        db,
        user=user,
        project_id=project.id,
        action="member_leave",
        entity_type="project_member",
        entity_id=member.id,
        detail={},
        commit=False,
    )


def transfer_ownership(
    db: Session, *, access, new_owner_user_id: str, reason: str | None = None
) -> Project:
    """所有权转移（事务内完成）：新 owner 必须是 active 成员。"""
    project = access.project
    if new_owner_user_id == access.user.id:
        raise ConflictError("你已经是项目所有者")
    target = get_member(db, project.id, new_owner_user_id)
    if target is None or target.status != MEMBER_STATUS_ACTIVE:
        raise ConflictError("只能将所有权转移给当前项目的有效成员")

    current_owner = get_member(db, project.id, access.user.id)
    if current_owner is not None:
        current_owner.role = PROJECT_ROLE_BID_MANAGER
    target.role = PROJECT_ROLE_OWNER
    target.status = MEMBER_STATUS_ACTIVE
    project.owner_id = new_owner_user_id
    project.revision = (project.revision or 1) + 1
    db.flush()

    notify(
        db,
        user_id=new_owner_user_id,
        type="ownership_transferred",
        title=f"你已成为项目「{project.name}」的所有者",
        project_id=project.id,
        link=f"/project/{project.id}/collaboration?tab=members",
        actor=access.user,
    )
    log_action(
        db,
        user=access.user,
        project_id=project.id,
        action="ownership_transfer",
        entity_type="project",
        entity_id=project.id,
        detail={
            "from_user_id": access.user.id,
            "to_user_id": new_owner_user_id,
            "reason": reason,
        },
        commit=False,
    )
    return project


def suspend_inactive_user_memberships(db: Session, user_id: str) -> int:
    """平台账号停用后：成员关系保留但不可继续操作。"""
    members = list(
        db.scalars(
            select(ProjectMember).where(
                ProjectMember.user_id == user_id,
                ProjectMember.status == MEMBER_STATUS_ACTIVE,
            )
        ).all()
    )
    for member in members:
        member.status = MEMBER_STATUS_SUSPENDED
    return len(members)


def restore_user_memberships(db: Session, user_id: str) -> int:
    members = list(
        db.scalars(
            select(ProjectMember).where(
                ProjectMember.user_id == user_id,
                ProjectMember.status == MEMBER_STATUS_SUSPENDED,
            )
        ).all()
    )
    for member in members:
        member.status = MEMBER_STATUS_ACTIVE
    return len(members)
