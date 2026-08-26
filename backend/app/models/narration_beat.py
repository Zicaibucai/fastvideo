"""旁白短句时间轴模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class NarrationBeat(BaseModel):
    __tablename__ = "narration_beats"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="CASCADE"), index=True, nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    shot_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    narration: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float] = mapped_column(nullable=False)
    end_time: Mapped[float] = mapped_column(nullable=False)
    evidence_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_references: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fact_check_status: Mapped[str] = mapped_column(String(16), default="unverified", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ai_done", nullable=False)

    project = relationship("Project")
    shot = relationship("StoryboardShot", back_populates="narration_beats")
