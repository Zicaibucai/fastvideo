"""统一 AI Provider 与业务环节绑定配置。"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AIConfiguration(BaseModel):
    __tablename__ = "ai_configurations"

    scope: Mapped[str] = mapped_column(String(32), unique=True, default="global", nullable=False)
    providers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stages: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
