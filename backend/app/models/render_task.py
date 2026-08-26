"""RenderTask AI 生成任务模型（任务队列状态跟踪）。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.status import StatusValidationMixin, TaskStatus


class RenderTask(StatusValidationMixin, BaseModel):
    __tablename__ = "render_tasks"
    VALID_STATUSES = frozenset(item.value for item in TaskStatus)

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="SET NULL"), index=True, nullable=True
    )
    task_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # parse_document | gen_narration | gen_image | gen_video | gen_tts | tts_batch | compose_video | export
    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.QUEUED.value, nullable=False, index=True
    )  # queued | running | success | failed | retry | cancelled

    # 批量父任务：子任务引用父任务 id（配音批量生成用）
    parent_task_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0-100

    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # 输入 / 输出
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 前端提示语
    message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    project = relationship("Project", back_populates="render_tasks")
    shot = relationship("StoryboardShot", lazy="selectin")
