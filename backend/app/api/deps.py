"""FastAPI 依赖注入。"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    # Browser sessions use an HttpOnly cookie. Bearer auth remains supported
    # for API clients and existing integrations.
    token = credentials.credentials if credentials else request.cookies.get("fastvideo_access")
    if not token:
        raise UnauthorizedError("未提供认证信息")
    payload = decode_access_token(token)
    if payload is None:
        raise UnauthorizedError("认证信息无效或已过期")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已停用")
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    token = credentials.credentials if credentials else request.cookies.get("fastvideo_access")
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user = db.get(User, payload.get("sub"))
    return user if user and user.is_active else None
