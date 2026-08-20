"""VoiceTemplate 配音模板模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class VoiceTemplate(BaseModel):
    __tablename__ = "voice_templates"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provider 与音色
    voice_provider: Mapped[str] = mapped_column(String(32), default="disabled", nullable=False)
    voice_name: Mapped[str] = mapped_column(String(64), default="onyx", nullable=False)  # 兼容旧字段
    provider_voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 新规范音色 ID
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 语言与音色风格
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    gender_style: Mapped[str] = mapped_column(String(16), default="male", nullable=False)  # male | female | neutral
    gender: Mapped[str] = mapped_column(String(8), default="male", nullable=False)  # 兼容旧字段
    age_style: Mapped[str | None] = mapped_column(String(16), nullable=True)
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 兼容旧字段（庄严/明快等）
    # speaking_style 预设：正式稳重/沉稳大气/科技专业/清晰客观/亲和自然/激昂有力/新闻播报/工程解说
    speaking_style: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 语音参数
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    pitch: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    pause_strength: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)  # 停顿强度
    emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 输出规格
    sample_rate: Mapped[int] = mapped_column(Integer, default=48000, nullable=False)
    audio_format: Mapped[str] = mapped_column(String(16), default="wav", nullable=False)  # wav | mp3

    # 发音词典（项目级，创建模板时可选绑定）
    pronunciation_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 授权
    # authorization_type: provider_builtin | enterprise_licensed | custom_authorized | mock | unknown
    authorization_type: Mapped[str] = mapped_column(String(32), default="provider_builtin", nullable=False)
    # authorization_status: approved | pending | rejected | expired | mock_only
    authorization_status: Mapped[str] = mapped_column(String(32), default="approved", nullable=False)
    authorization_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorization_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 试听音频
    preview_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    preview_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project = relationship("Project", back_populates="voice_templates")
    preview_asset = relationship("Asset", lazy="selectin")

    @property
    def effective_voice_id(self) -> str:
        """优先使用新规范音色 ID，其次回退旧字段 voice_name。"""
        return self.provider_voice_id or self.voice_name

    @property
    def effective_speaking_style(self) -> str:
        """speaking_style 优先，其次兼容旧 style 字段。"""
        return self.speaking_style or self.style or "正式稳重"
