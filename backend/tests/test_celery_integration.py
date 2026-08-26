"""真实 Redis + Celery 集成测试。

默认不参与普通单元测试；在 Docker Compose 已启动时运行：
FASTVIDEO_CELERY_INTEGRATION=1 pytest -q backend/tests/test_celery_integration.py
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
def test_real_redis_celery_round_trip() -> None:
    if os.getenv("FASTVIDEO_CELERY_INTEGRATION") != "1":
        pytest.skip("设置 FASTVIDEO_CELERY_INTEGRATION=1 才运行真实 Redis/Celery 测试")

    from app.tasks.celery_app import celery_app

    with celery_app.connection_for_read() as connection:
        connection.ensure_connection(max_retries=1)

    result = celery_app.send_task("fastvideo.health_probe", args=["integration-ok"])
    assert result.get(timeout=20) == {"value": "integration-ok"}
