"""Celery 任务注册守卫：worker 按 include 列表显式加载任务模块，

新增任务模块忘了加进 include 时，任务消息会被 worker 当作
unregistered task 丢弃，前端任务永远停在 queued（本文件防回归）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tasks.celery_app import celery_app  # noqa: E402

TASKS_DIR = Path(__file__).resolve().parent.parent / "app" / "tasks"


def _modules_defining_celery_tasks() -> set[str]:
    modules: set[str] = set()
    for path in TASKS_DIR.glob("*.py"):
        if path.name in ("__init__.py", "celery_app.py"):
            continue
        if re.search(r"@celery_app\.task", path.read_text(encoding="utf-8")):
            modules.add(f"app.tasks.{path.stem}")
    return modules


def test_all_task_modules_are_included() -> None:
    include = set(celery_app.conf.include or [])
    missing = _modules_defining_celery_tasks() - include
    assert not missing, f"任务模块未加入 celery include，worker 将无法执行: {sorted(missing)}"


def test_new_pipeline_tasks_registered() -> None:
    # include 列表在 worker 启动时才真正 import，这里显式导入模拟该过程
    import app.tasks.custom_segment  # noqa: F401
    import app.tasks.video_concat  # noqa: F401

    registered = set(celery_app.tasks.keys())
    for name in ("fastvideo.concat_videos", "fastvideo.custom_segment"):
        assert name in registered, f"{name} 未注册"
