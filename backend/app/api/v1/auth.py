"""认证与用户路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.common import Message
from app.schemas.user import LoginRequest, Token, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=Token, summary="登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("邮箱或密码错误")
    if not user.is_active:
        raise UnauthorizedError("账号已停用")
    return Token(access_token=create_access_token(subject=user.id))


@router.post("/register", response_model=UserOut, status_code=201, summary="注册")
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise ConflictError("该邮箱已注册")
    user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        company=payload.company,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut, summary="当前用户")
def me(current: User = Depends(get_current_user)) -> User:
    return current


@router.patch("/me", response_model=UserOut, summary="更新当前用户")
def update_me(
    payload: UserUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    data = payload.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        data["hashed_password"] = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(current, field, value)
    db.commit()
    db.refresh(current)
    return current
