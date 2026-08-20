"""认证与安全工具：密码哈希（标准库 PBKDF2-SHA256）+ JWT。

使用 Python 标准库实现密码哈希，避免 passlib/bcrypt 版本兼容性问题。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 小时

# PBKDF2 参数
_PBKDF2_ITERATIONS = 200_000
_HASH_ALGO = "sha256"
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 哈希密码，返回 `pbkdf2$iterations$salt$hash`。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _HASH_ALGO, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ITERATIONS,
        salt.hex(),
        digest.hex(),
    )


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。兼容 pbkdf2 格式；如遇旧格式返回 False。"""
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
        digest = hashlib.pbkdf2_hmac(
            _HASH_ALGO, plain.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {"sub": subject, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None
