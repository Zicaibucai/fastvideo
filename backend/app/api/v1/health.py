"""健康检查与系统状态路由（无需认证）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.factory import ai_status
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["系统"])


@router.get("/health", summary="健康检查")
def health(db: Session = Depends(get_db)) -> dict:
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    celery_status = "disabled"
    if settings.use_celery:
        client = None
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            celery_status = "ok"
        except Exception:
            celery_status = "error"
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    overall = "ok" if db_status == "ok" and celery_status in {"ok", "disabled"} else "degraded"
    return {
        "status": overall,
        "app": settings.app_name,
        "env": settings.app_env,
        "database": db_status,
        "storage": settings.storage_backend,
        "celery": celery_status,
    }


@router.get("/system/status", summary="系统状态（含 AI 服务状态）")
def system_status() -> dict:
    return {
        "app": settings.app_name,
        "version": "0.1.0",
        "env": settings.app_env,
        "ai": ai_status(),
        "ffmpeg": settings.ffmpeg_binary,
    }
