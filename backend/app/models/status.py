"""集中定义业务状态，避免状态字符串在各模块漂移。"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from sqlalchemy.orm import validates


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


class VideoProjectStatus(StrEnum):
    DRAFT = "draft"
    COMPOSING = "composing"
    SUCCESS = "success"
    FAILED = "failed"


class NarrationRunStatus(StrEnum):
    CREATED = "created"
    EVIDENCE_EXTRACTING = "evidence_extracting"
    EVIDENCE_REVIEW = "evidence_review"
    EVIDENCE_FAILED = "evidence_failed"
    OUTLINE_GENERATING = "outline_generating"
    OUTLINE_REVIEW = "outline_review"
    DRAFTING = "drafting"
    DRAFTING_FAILED = "drafting_failed"
    QA = "qa"
    QA_FAILED = "qa_failed"
    COMPLETED = "completed"


class StatusValidationMixin:
    """在 ORM 写入边界校验状态；数据库迁移前也能阻止拼写错误。"""

    VALID_STATUSES: ClassVar[frozenset[str]] = frozenset()

    @validates("status")
    def validate_status(self, _key: str, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in self.VALID_STATUSES:
            allowed = ", ".join(sorted(self.VALID_STATUSES))
            raise ValueError(f"无效状态 {value!r}，允许值：{allowed}")
        return normalized
