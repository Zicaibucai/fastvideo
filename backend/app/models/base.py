"""数据库模型的公共基类与工具。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uuid_str() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    """返回带 UTC 时区信息的当前时间，作为业务时间戳唯一入口。"""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """兼容历史 String 时间列的 ISO-8601 UTC 表示。"""
    return utc_now().isoformat(timespec="seconds")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPKMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=uuid_str, index=True
    )


class BaseModel(Base, UUIDPKMixin, TimestampMixin):
    """所有业务表的基类：UUID 主键 + 创建/更新时间戳。"""

    __abstract__ = True

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for col in self.__table__.columns:
            value = getattr(self, col.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[col.name] = value
        return result
