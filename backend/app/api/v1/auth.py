"""认证与用户路由。"""

from __future__ import annotations

import time
from collections import defaultdict
from hashlib import sha256
from threading import Lock

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, RateLimitError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.common import Message
from app.schemas.user import LoginRequest, Token, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/auth", tags=["认证"])

_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 10
_LOGIN_MAX_TRACKED_KEYS = 10_000
_login_failures: dict[str, list[float]] = defaultdict(list)
_login_lock = Lock()
_login_redis = None
_login_redis_retry_at = 0.0


def _get_login_redis():
    """Return a shared limiter backend when Celery/Redis is enabled.

    The in-memory implementation remains a safe fallback for local development,
    while production workers share counters through Redis.
    """
    global _login_redis, _login_redis_retry_at
    if not settings.use_celery:
        return None
    now = time.monotonic()
    if _login_redis is not None:
        return _login_redis
    if now < _login_redis_retry_at:
        return None
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        client.ping()
        _login_redis = client
        return client
    except Exception:
        _login_redis_retry_at = now + 30
        return None


def _disable_login_redis() -> None:
    global _login_redis, _login_redis_retry_at
    _login_redis = None
    _login_redis_retry_at = time.monotonic() + 30


def _redis_failure_key(key: str) -> str:
    return f"fastvideo:login-failure:{sha256(key.encode('utf-8')).hexdigest()}"


def _login_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{email.strip().lower()}"


def _login_limited(key: str, now: float) -> bool:
    redis_client = _get_login_redis()
    if redis_client is not None:
        try:
            return int(redis_client.get(_redis_failure_key(key)) or 0) >= _LOGIN_MAX_FAILURES
        except Exception:
            _disable_login_redis()
    with _login_lock:
        recent = [stamp for stamp in _login_failures[key] if now - stamp < _LOGIN_WINDOW_SECONDS]
        _login_failures[key] = recent
        return len(recent) >= _LOGIN_MAX_FAILURES


def _record_login_failure(key: str, now: float) -> None:
    redis_client = _get_login_redis()
    if redis_client is not None:
        try:
            redis_key = _redis_failure_key(key)
            count = redis_client.incr(redis_key)
            if count == 1:
                redis_client.expire(redis_key, _LOGIN_WINDOW_SECONDS)
            return
        except Exception:
            _disable_login_redis()
    with _login_lock:
        _login_failures[key] = [stamp for stamp in _login_failures[key] if now - stamp < _LOGIN_WINDOW_SECONDS]
        _login_failures[key].append(now)
        # Bound the fallback in-memory limiter so an attacker cannot grow it
        # without limit by submitting unique email addresses.
        if len(_login_failures) > _LOGIN_MAX_TRACKED_KEYS:
            stale_keys = [
                tracked_key
                for tracked_key, stamps in _login_failures.items()
                if not stamps or now - stamps[-1] >= _LOGIN_WINDOW_SECONDS
            ]
            for tracked_key in stale_keys:
                _login_failures.pop(tracked_key, None)
            while len(_login_failures) > _LOGIN_MAX_TRACKED_KEYS:
                oldest_key = min(
                    _login_failures,
                    key=lambda tracked_key: _login_failures[tracked_key][-1],
                )
                _login_failures.pop(oldest_key, None)


def _clear_login_failures(key: str) -> None:
    redis_client = _get_login_redis()
    if redis_client is not None:
        try:
            redis_client.delete(_redis_failure_key(key))
            return
        except Exception:
            _disable_login_redis()
    with _login_lock:
        _login_failures.pop(key, None)


@router.post("/login", response_model=Token, summary="登录")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> Token:
    key = _login_key(request, payload.email)
    now = time.monotonic()
    if _login_limited(key, now):
        raise RateLimitError("登录失败次数过多，请 15 分钟后重试")
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.hashed_password):
        _record_login_failure(key, now)
        raise UnauthorizedError("邮箱或密码错误")
    if not user.is_active:
        raise UnauthorizedError("账号已停用")
    _clear_login_failures(key)
    access_token = create_access_token(subject=user.id)
    # Browser sessions use an HttpOnly cookie; the JSON token remains for
    # non-browser API clients and backwards compatibility.
    response.set_cookie(
        key="fastvideo_access",
        value=access_token,
        max_age=60 * 24 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return Token(access_token=access_token)


@router.post("/logout", summary="退出登录")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(key="fastvideo_access", path="/")
    return {"message": "已退出登录"}


@router.post("/register", response_model=UserOut, status_code=201, summary="注册")
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    if not settings.allow_public_registration:
        raise ForbiddenError("当前系统关闭公开注册，请联系管理员创建账号")
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
