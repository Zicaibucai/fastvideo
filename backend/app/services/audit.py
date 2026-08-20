"""审计日志辅助服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def log_action(
    db: Session,
    *,
    user: User | None,
    project_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    note: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """记录一条审计日志。

    commit=True 时立即提交；否则由调用方在事务末尾统一提交。
    """
    log = AuditLog(
        user_id=user.id if user else None,
        user_name=user.username if user else None,
        project_id=project_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
        ip_address=ip_address,
        note=note,
    )
    db.add(log)
    if commit:
        db.commit()
    return log
