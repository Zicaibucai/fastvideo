"""Celery 应用配置。

- Redis 作为 broker 与 backend。
- USE_CELERY=false 时（本地无 Redis），前端仍可运行：API 会同步执行任务并直接更新数据库。
  因此所有任务函数必须把业务逻辑放在纯函数中，便于同步/异步两用。
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "fastvideo",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.narration",
        "app.tasks.assets",
        "app.tasks.export",
        "app.tasks.document_parse",
        "app.tasks.render",
        "app.tasks.voice",
        "app.tasks.video_export",
        "app.tasks.video_gen",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=settings.celery_task_track_started,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_max_tasks_per_child=200,
    task_default_queue="fastvideo",
    task_default_exchange="fastvideo",
    task_default_routing_key="fastvideo",
    broker_connection_retry_on_startup=True,
    task_time_limit=3600,          # 单任务最长 1 小时
    task_soft_time_limit=3300,
    result_expires=3600 * 24 * 7,
)
