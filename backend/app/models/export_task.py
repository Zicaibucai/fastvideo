"""ExportTask 导出任务模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ExportTask(BaseModel):
    __tablename__ = "export_tasks"

    video_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    export_format: Mapped[str] = mapped_column(String(16), default="mp4", nullable=False)
    # 导出模式：demo | formal
    mode: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="queued", nullable=False, index=True
    )  # queued | running | success | failed | retry | cancelled
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 输出
    output_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)

    # Phase 5：独立 SRT 与导出报告
    srt_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 导出时间轴快照（历史成片可追溯）
    timeline_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    video_project = relationship("VideoProject", back_populates="export_tasks")

    @property
    def srt_url(self) -> str | None:
        """由存储 key 派生可访问的 SRT URL。

        URL 属于运行时存储配置，不单独入库，避免切换
        local/MinIO 后保留过期地址。
        """
        if not self.srt_key:
            return None
        from app.core.storage import storage

        return storage.url(self.srt_key)

    @property
    def report_url(self) -> str | None:
        """由存储 key 派生可访问的导出报告 URL。"""
        if not self.report_key:
            return None
        from app.core.storage import storage

        return storage.url(self.report_key)
