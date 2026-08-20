"""AuditLog 审计日志模型。

记录模板创建/修改、音色试听、配音任务创建、批量生成等敏感操作。
"""

from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AuditLog(BaseModel):
    __tablename__ = "audit_logs"

    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)

    # 动作：voice_template_create/update/delete/duplicate | voice_preview
    #      | voice_generate | voice_batch | voice_select | voice_restore
    #      | voice_version_delete | pronunciation_import | etc.
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
