"""统一项目权限服务：项目级 RBAC。

所有项目访问控制必须经由本模块，禁止在各接口中继续手写
`project.owner_id == user.id` 判断。

错误策略：
- 非项目成员访问 → 404（不泄露项目存在性）
- 项目成员但权限不足 → 403
- 超级管理员绕行访问全部写审计日志（读访问按 1 小时去重，写访问逐条记录）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.base import utc_now
from app.models.collaboration import (
    MEMBER_STATUS_ACTIVE,
    PROJECT_ROLE_BID_MANAGER,
    PROJECT_ROLE_MEDIA_EDITOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_REVIEWER,
    PROJECT_ROLE_TECHNICAL_EDITOR,
    PROJECT_ROLE_VIEWER,
    ProjectMember,
)
from app.models.project import Project
from app.models.user import User

# ---- 细粒度权限 ----
PERM_PROJECT_VIEW = "project.view"
PERM_PROJECT_EDIT = "project.edit"
PERM_PROJECT_DELETE = "project.delete"
PERM_MEMBER_VIEW = "member.view"
PERM_MEMBER_MANAGE = "member.manage"
PERM_OWNERSHIP_TRANSFER = "ownership.transfer"
PERM_REVIEW_POLICY = "review.policy"
PERM_DOCUMENT_VIEW = "document.view"
PERM_DOCUMENT_UPLOAD = "document.upload"
PERM_DOCUMENT_EDIT = "document.edit"
PERM_FACT_VIEW = "fact.view"
PERM_FACT_EDIT = "fact.edit"
PERM_SCORING_VIEW = "scoring.view"
PERM_SCORING_EDIT = "scoring.edit"
PERM_STORYBOARD_VIEW = "storyboard.view"
PERM_STORYBOARD_EDIT = "storyboard.edit"
PERM_MEDIA_VIEW = "media.view"      # 画面制作 / 素材库 / AI 视频
PERM_MEDIA_EDIT = "media.edit"
PERM_VOICE_VIEW = "voice.view"
PERM_VOICE_EDIT = "voice.edit"
PERM_VIDEO_VIEW = "video.view"      # 视频工程
PERM_VIDEO_EDIT = "video.edit"
PERM_REVIEW_VIEW = "review.view"
PERM_REVIEW_SUBMIT = "review.submit"
PERM_REVIEW_DECIDE = "review.decide"
PERM_COMMENT_VIEW = "comment.view"
PERM_COMMENT_CREATE = "comment.create"
PERM_COMMENT_RESOLVE = "comment.resolve"
PERM_TASK_VIEW = "task.view"
PERM_TASK_CREATE = "task.create"
PERM_TASK_ASSIGN = "task.assign"
PERM_TASK_UPDATE = "task.update"    # 更新自己相关待办状态
PERM_AUDIT_VIEW = "audit.view"
PERM_EXPORT_VIEW = "export.view"
PERM_EXPORT_DEMO = "export.demo"
PERM_EXPORT_FORMAL = "export.formal"
PERM_ADMIN_OVERRIDE = "admin.override"

ALL_PERMISSIONS = frozenset({
    PERM_PROJECT_VIEW, PERM_PROJECT_EDIT, PERM_PROJECT_DELETE,
    PERM_MEMBER_VIEW, PERM_MEMBER_MANAGE, PERM_OWNERSHIP_TRANSFER, PERM_REVIEW_POLICY,
    PERM_DOCUMENT_VIEW, PERM_DOCUMENT_UPLOAD, PERM_DOCUMENT_EDIT,
    PERM_FACT_VIEW, PERM_FACT_EDIT, PERM_SCORING_VIEW, PERM_SCORING_EDIT,
    PERM_STORYBOARD_VIEW, PERM_STORYBOARD_EDIT,
    PERM_MEDIA_VIEW, PERM_MEDIA_EDIT, PERM_VOICE_VIEW, PERM_VOICE_EDIT,
    PERM_VIDEO_VIEW, PERM_VIDEO_EDIT,
    PERM_REVIEW_VIEW, PERM_REVIEW_SUBMIT, PERM_REVIEW_DECIDE,
    PERM_COMMENT_VIEW, PERM_COMMENT_CREATE, PERM_COMMENT_RESOLVE,
    PERM_TASK_VIEW, PERM_TASK_CREATE, PERM_TASK_ASSIGN, PERM_TASK_UPDATE,
    PERM_AUDIT_VIEW, PERM_EXPORT_VIEW, PERM_EXPORT_DEMO, PERM_EXPORT_FORMAL,
    PERM_ADMIN_OVERRIDE,
})

_VIEW_PERMISSIONS = frozenset({
    PERM_PROJECT_VIEW, PERM_MEMBER_VIEW, PERM_DOCUMENT_VIEW, PERM_FACT_VIEW,
    PERM_SCORING_VIEW, PERM_STORYBOARD_VIEW, PERM_MEDIA_VIEW, PERM_VOICE_VIEW,
    PERM_VIDEO_VIEW, PERM_REVIEW_VIEW, PERM_COMMENT_VIEW, PERM_TASK_VIEW,
    PERM_EXPORT_VIEW,
})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    PROJECT_ROLE_OWNER: ALL_PERMISSIONS,
    PROJECT_ROLE_BID_MANAGER: frozenset({
        *_VIEW_PERMISSIONS,
        PERM_PROJECT_EDIT,
        PERM_DOCUMENT_UPLOAD, PERM_DOCUMENT_EDIT,
        PERM_FACT_EDIT, PERM_SCORING_EDIT,
        PERM_STORYBOARD_EDIT, PERM_MEDIA_EDIT, PERM_VOICE_EDIT, PERM_VIDEO_EDIT,
        PERM_REVIEW_SUBMIT,
        PERM_COMMENT_CREATE, PERM_COMMENT_RESOLVE,
        PERM_TASK_CREATE, PERM_TASK_ASSIGN, PERM_TASK_UPDATE,
        PERM_EXPORT_DEMO, PERM_EXPORT_FORMAL,
    }),
    PROJECT_ROLE_TECHNICAL_EDITOR: frozenset({
        *_VIEW_PERMISSIONS,
        PERM_DOCUMENT_UPLOAD, PERM_DOCUMENT_EDIT,
        PERM_FACT_EDIT, PERM_SCORING_EDIT,
        PERM_REVIEW_SUBMIT,
        PERM_COMMENT_CREATE, PERM_COMMENT_RESOLVE,
        PERM_TASK_CREATE, PERM_TASK_UPDATE,
        PERM_EXPORT_DEMO,
    }),
    PROJECT_ROLE_MEDIA_EDITOR: frozenset({
        *_VIEW_PERMISSIONS,
        PERM_STORYBOARD_EDIT, PERM_MEDIA_EDIT, PERM_VOICE_EDIT, PERM_VIDEO_EDIT,
        PERM_REVIEW_SUBMIT,
        PERM_COMMENT_CREATE, PERM_COMMENT_RESOLVE,
        PERM_TASK_CREATE, PERM_TASK_UPDATE,
        PERM_EXPORT_DEMO,
    }),
    PROJECT_ROLE_REVIEWER: frozenset({
        *_VIEW_PERMISSIONS,
        PERM_REVIEW_DECIDE,
        PERM_COMMENT_CREATE, PERM_COMMENT_RESOLVE,
        PERM_TASK_CREATE,  # 审核意见可转为待办
    }),
    PROJECT_ROLE_VIEWER: frozenset({
        *_VIEW_PERMISSIONS,
    }),
}

ROLE_LABELS: dict[str, str] = {
    PROJECT_ROLE_OWNER: "项目所有者",
    PROJECT_ROLE_BID_MANAGER: "投标负责人",
    PROJECT_ROLE_TECHNICAL_EDITOR: "技术编辑",
    PROJECT_ROLE_MEDIA_EDITOR: "视频编辑",
    PROJECT_ROLE_REVIEWER: "审核人",
    PROJECT_ROLE_VIEWER: "只读成员",
}

# 写操作权限集合（超管绕行时逐条审计；读访问按时间窗去重）
_WRITE_PERMISSIONS = ALL_PERMISSIONS - _VIEW_PERMISSIONS


@dataclass
class ProjectAccess:
    """一次项目访问的完整上下文。"""

    project: Project
    member: ProjectMember | None  # 超管绕行时为 None
    role: str
    permissions: frozenset[str]
    user: User
    is_admin_bypass: bool = False
    extra: dict = field(default_factory=dict)

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise ForbiddenError(f"当前角色缺少权限：{permission}")


def permissions_for_role(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def get_member(db: Session, project_id: str, user_id: str) -> ProjectMember | None:
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )


def ensure_owner_member(db: Session, project: Project) -> ProjectMember:
    """确保项目 owner 存在 active 成员记录（迁移回填之外的兜底，如新建项目）。"""
    member = get_member(db, project.id, project.owner_id)
    if member is None:
        member = ProjectMember(
            project_id=project.id,
            user_id=project.owner_id,
            role=PROJECT_ROLE_OWNER,
            status=MEMBER_STATUS_ACTIVE,
        )
        db.add(member)
        db.flush()
    elif member.role != PROJECT_ROLE_OWNER or member.status != MEMBER_STATUS_ACTIVE:
        member.role = PROJECT_ROLE_OWNER
        member.status = MEMBER_STATUS_ACTIVE
        db.flush()
    return member


def _log_admin_bypass(db: Session, user: User, project: Project, permission: str) -> None:
    """超级管理员绕行访问留审计。写操作逐条记录；读操作 1 小时内去重。"""
    from app.services.audit import log_action

    is_write = permission in _WRITE_PERMISSIONS
    if not is_write:
        from app.models.audit_log import AuditLog

        since = utc_now() - timedelta(hours=1)
        recent = db.scalar(
            select(AuditLog.id).where(
                AuditLog.user_id == user.id,
                AuditLog.project_id == project.id,
                AuditLog.action == "admin_project_access",
                AuditLog.created_at >= since,
            ).limit(1)
        )
        if recent:
            return
    log_action(
        db,
        user=user,
        project_id=project.id,
        action="admin_project_access" if not is_write else "admin_project_write",
        entity_type="project",
        entity_id=project.id,
        detail={"permission": permission, "via": "superuser_bypass"},
        note="超级管理员绕行项目权限",
        # 只读接口通常不再 commit，读绕行审计需立即落库；写绕行随业务事务提交
        commit=not is_write,
    )


def get_project_access(
    db: Session,
    project_id: str,
    user: User,
    permission: str = PERM_PROJECT_VIEW,
) -> ProjectAccess:
    """统一项目访问入口。

    - 项目不存在或用户不是有效成员（且非超管）→ 404
    - 成员但缺少指定权限 → 403
    - 超级管理员绕行 → 放行并写审计
    """
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")

    member = get_member(db, project.id, user.id)
    if member is not None and member.status != MEMBER_STATUS_ACTIVE:
        member = None  # 停用/退出成员不可继续操作

    if member is None and project.owner_id == user.id:
        # 兜底：owner 成员记录缺失时自动修复（如历史数据或测试直插）
        member = ensure_owner_member(db, project)

    if member is not None:
        access = ProjectAccess(
            project=project,
            member=member,
            role=member.role,
            permissions=permissions_for_role(member.role),
            user=user,
        )
        access.require(permission)
        return access

    if user.is_superuser:
        _log_admin_bypass(db, user, project, permission)
        return ProjectAccess(
            project=project,
            member=None,
            role="superuser",
            permissions=ALL_PERMISSIONS,
            user=user,
            is_admin_bypass=True,
        )

    raise NotFoundError("项目不存在")


def require_project_permission(
    db: Session,
    project_id: str,
    user: User,
    permission: str,
) -> ProjectAccess:
    return get_project_access(db, project_id, user, permission)


def active_members(db: Session, project_id: str) -> list[ProjectMember]:
    return list(
        db.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.status == MEMBER_STATUS_ACTIVE,
            )
        ).all()
    )


def assert_active_member(db: Session, project_id: str, user_id: str) -> ProjectMember:
    member = get_member(db, project_id, user_id)
    if member is None or member.status != MEMBER_STATUS_ACTIVE:
        raise ForbiddenError("目标用户不是当前项目的有效成员")
    return member


def accessible_project_ids(db: Session, user: User) -> list[str] | None:
    """用户可访问的项目 ID 列表；超管返回 None 表示全部。"""
    if user.is_superuser:
        return None
    ids = set(
        db.scalars(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id,
                ProjectMember.status == MEMBER_STATUS_ACTIVE,
            )
        ).all()
    )
    # 兜底：尚未回填成员关系的历史项目
    ids |= set(db.scalars(select(Project.id).where(Project.owner_id == user.id)).all())
    return list(ids)
