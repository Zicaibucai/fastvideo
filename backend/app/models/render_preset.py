"""RenderPreset 渲染风格预设模型。

内置 12 种系统预设 + 企业自定义预设。系统预设普通用户只能使用，
管理员可启用/停用/复制为企业预设。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class RenderPreset(BaseModel):
    __tablename__ = "render_presets"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_image: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_positive_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_aspect_ratio: Mapped[str] = mapped_column(String(16), default="16:9", nullable=False)
    recommended_structure_strength: Mapped[int] = mapped_column(Integer, default=85, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 排序
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 来源预设（企业复制自系统预设时记录）
    source_preset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
