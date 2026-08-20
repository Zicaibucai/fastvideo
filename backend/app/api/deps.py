"""FastAPI 依赖注入。"""

from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise UnauthorizedError("未提供认证信息")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise UnauthorizedError("认证信息无效或已过期")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已停用")
    return user


def get_optional_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        return None
    return db.get(User, payload.get("sub"))
