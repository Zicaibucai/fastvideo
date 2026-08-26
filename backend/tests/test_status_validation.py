from __future__ import annotations

import pytest

from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.status import TaskStatus


def test_task_status_enum_values_are_stable() -> None:
    assert TaskStatus.QUEUED.value == "queued"
    assert TaskStatus.CANCELLED.value == "cancelled"


def test_orm_rejects_unknown_task_status() -> None:
    with pytest.raises(ValueError, match="无效状态"):
        RenderTask(status="in_progress")


def test_orm_rejects_unknown_storyboard_status() -> None:
    with pytest.raises(ValueError, match="无效状态"):
        StoryboardShot(status="done")
