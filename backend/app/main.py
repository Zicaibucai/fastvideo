"""FastAPI 应用入口。

- 初始化数据库（首次启动自动建表 + 创建管理员 + 种子数据）
- 注册统一异常处理、CORS、静态文件
- 挂载 v1 路由
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.models import *  # noqa: F401,F403  （注册所有模型）

logger = get_logger(__name__)


def _init_db() -> None:
    """首次启动：建表 + 管理员 + 系统配音模板种子。"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("database_tables_ready")
    except Exception as exc:
        logger.exception("database_init_failed", error=str(exc))
        return

    db = SessionLocal()
    try:
        from app.core.security import hash_password
        from app.models.user import User
        from sqlalchemy import select

        # 管理员
        existing = db.scalar(
            select(User).where(User.email == settings.admin_email)
        )
        if not existing:
            admin = User(
                email=settings.admin_email,
                username="admin",
                full_name="系统管理员",
                company="系统",
                hashed_password=hash_password(settings.admin_password),
                is_superuser=True,
            )
            db.add(admin)
            db.commit()
            logger.info("admin_created", email=settings.admin_email)

        # 系统配音模板
        from app.api.v1.voices import seed_default_voice_templates

        seed_default_voice_templates(db)

        # 火山引擎豆包语音合成音色模板（幂等）
        from app.api.v1.voices import seed_volcengine_voice_templates

        seed_volcengine_voice_templates(db)

        # 系统发音词典
        from app.services.pronunciation_service import seed_system_pronunciation

        seed_system_pronunciation(db)

        # 系统渲染预设
        from app.api.v1.render_presets import seed_system_presets

        seed_system_presets(db)

        # 系统 AI 视频生成模板（10 个建筑视频模板）
        from app.services.video_gen_service import seed_video_generation_templates

        seed_video_generation_templates(db)
    except Exception as exc:
        logger.exception("seed_failed", error=str(exc))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("fastvideo_start", env=settings.app_env, db=settings.database_url)
    _init_db()
    yield
    logger.info("fastvideo_stop")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="建筑工程AI投标视频平台 API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一异常处理
register_exception_handlers(app)

# 静态文件（前端构建产物可选挂载）
try:
    from app.core.config import PROJECT_ROOT

    frontend_dist = PROJECT_ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dist)), name="static")
except Exception:
    pass

# 路由
from app.api.v1 import (  # noqa: E402
    assets,
    auth,
    documents,
    facts,
    files,
    health,
    projects,
    reader,
    render,
    render_presets,
    scoring,
    storyboard,
    tasks,
    video,
    video_gen,
    voice,
    voices,
)

api_prefix = settings.api_v1_prefix
app.include_router(health.router, prefix=api_prefix)
app.include_router(auth.router, prefix=api_prefix)
app.include_router(projects.router, prefix=api_prefix)
app.include_router(documents.router, prefix=api_prefix)
app.include_router(reader.router, prefix=api_prefix)
app.include_router(facts.router, prefix=api_prefix)
app.include_router(scoring.router, prefix=api_prefix)
app.include_router(storyboard.router, prefix=api_prefix)
app.include_router(assets.router, prefix=api_prefix)
app.include_router(tasks.router, prefix=api_prefix)
app.include_router(voices.router, prefix=api_prefix)
app.include_router(voices.global_router, prefix=api_prefix)
app.include_router(voice.pronunciation_router, prefix=api_prefix)
app.include_router(voice.voice_router, prefix=api_prefix)
app.include_router(voice.shot_voice_router, prefix=api_prefix)
app.include_router(video.router, prefix=api_prefix)
app.include_router(video_gen.router, prefix=api_prefix)
app.include_router(render_presets.router, prefix=api_prefix)
app.include_router(render.router, prefix=api_prefix)
app.include_router(files.router)


@app.get("/", tags=["系统"])
def root() -> dict:
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "health": f"{api_prefix}/health",
        "status": f"{api_prefix}/system/status",
    }
