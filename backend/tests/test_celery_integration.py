"""真实 Redis + Celery 集成测试。

默认不参与普通单元测试；在 Docker Compose 已启动时运行：
FASTVIDEO_CELERY_INTEGRATION=1 pytest -q backend/tests/test_celery_integration.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def celery_worker() -> Iterator[subprocess.Popen[str]]:
    """Start a real Celery worker against the configured Redis broker.

    The fixture keeps the test runnable from a developer checkout even when
    Docker's Redis port is not exposed on localhost (for example, when a
    system Redis already owns port 6379).
    """
    if os.getenv("FASTVIDEO_CELERY_INTEGRATION") != "1":
        pytest.skip("设置 FASTVIDEO_CELERY_INTEGRATION=1 才运行真实 Redis/Celery 测试")

    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_root)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks.celery_app:celery_app",
            "worker",
            "--pool=solo",
            "--loglevel=WARNING",
            "--queues=fastvideo",
        ],
        cwd=backend_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(1)
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.integration
def test_real_redis_celery_round_trip(celery_worker: subprocess.Popen[str]) -> None:
    from app.tasks.celery_app import celery_app

    with celery_app.connection_for_read() as connection:
        connection.ensure_connection(max_retries=1)

    result = celery_app.send_task("fastvideo.health_probe", args=["integration-ok"])
    assert result.get(timeout=20) == {"value": "integration-ok"}
