"""站内通知服务。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.collaboration import Notification
from app.models.user import User


def notify(
    db: Session,
    *,
    user_id: str | None,
    type: str,
    title: str,
    body: str | None = None,
    project_id: str | None = None,
    link: str | None = None,
    actor: User | None = None,
) -> Notification | None:
    """写入一条站内通知（不通知操作者本人）。调用方负责提交事务。"""
    if not user_id:
        return None
    if actor is not None and actor.id == user_id:
        return None
    item = Notification(
        user_id=user_id,
        project_id=project_id,
        type=type,
        title=title[:255],
        body=body,
        link=link,
        actor_id=actor.id if actor else None,
    )
    db.add(item)
    return item
