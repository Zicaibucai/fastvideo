"""Admin 人员系统：仅超级管理员可访问。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserUpdate, UserOut

router = APIRouter(prefix="/admin", tags=["Admin 人员系统"])


def require_superuser(current: User = Depends(get_current_user)) -> User:
    if not current.is_superuser:
        raise ForbiddenError("仅超级管理员可以管理平台人员")
    return current


def _superuser_count(db: Session, *, active_only: bool = False) -> int:
    query = select(func.count(User.id)).where(User.is_superuser.is_(True))
    if active_only:
        query = query.where(User.is_active.is_(True))
    return int(db.scalar(query) or 0)


@router.get("/users", response_model=list[UserOut], summary="人员列表")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_superuser),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())).all())


@router.post("/users", response_model=UserOut, status_code=201, summary="添加人员")
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superuser),
) -> User:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise ConflictError("该邮箱已注册")
    user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        company=payload.company,
        hashed_password=hash_password(payload.password),
        is_superuser=payload.is_superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut, summary="更新人员")
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_superuser),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("人员不存在")

    data = payload.model_dump(exclude_unset=True)
    next_is_active = data.get("is_active", user.is_active)
    next_is_superuser = data.get("is_superuser", user.is_superuser)

    if user.id == current.id and (next_is_active is False or next_is_superuser is False):
        raise ConflictError("不能停用当前账号或取消自己的管理员权限")
    if user.is_superuser and user.is_active and (next_is_active is False or next_is_superuser is False):
        if _superuser_count(db, active_only=True) <= 1:
            raise ConflictError("系统至少需要保留一名正常状态的超级管理员")

    if "password" in data and data["password"]:
        data["hashed_password"] = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
