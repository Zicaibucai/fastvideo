"""FastAPI 应用入口。

- 初始化数据库（首次启动自动建表 + 创建管理员 + 种子数据）
- 注册统一异常处理、CORS、静态文件
- 挂载 v1 路由
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.models import *  # noqa: F401,F403  （注册所有模型）

logger = get_logger(__name__)


def _run_schema_migrations() -> bool:
    """启动时补齐未执行的 Alembic 迁移，兼容已有开发数据库。"""
    try:
        from alembic import command
        from alembic.config import Config

        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not alembic_ini.exists():
            return False
        config = Config(str(alembic_ini))
        # Alembic resolves relative paths against the current working
        # directory, which differs between `uvicorn`, tests, and containers.
        # Pin both locations to the backend directory next to alembic.ini.
        config.set_main_option("script_location", str(alembic_ini.parent / "alembic"))
        config.set_main_option("prepend_sys_path", str(alembic_ini.parent))
        # ConfigParser treats `%` as interpolation syntax; URL-encoded database
        # passwords must therefore be escaped before being passed to Alembic.
        config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url.replace("%", "%%"))
        command.upgrade(config, "head")
        logger.info("database_migrations_ready")
        return True
    except Exception as exc:
        logger.exception("database_migration_failed", error=str(exc))
        return False


def _init_db() -> None:
    """首次启动：建表 + 管理员 + 系统配音模板种子。"""
    try:
        if not _run_schema_migrations():
            raise RuntimeError("数据库迁移未完成，拒绝启动以避免使用不一致的 schema")
        # Alembic is authoritative in production.  Keep create_all only as a
        # convenience for local demo databases after migrations succeed.
        if settings.app_env.lower() not in {"prod", "production"}:
            Base.metadata.create_all(bind=engine)
        logger.info("database_tables_ready")
    except Exception as exc:
        logger.exception("database_init_failed", error=str(exc))
        raise

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

        # 系统 AI 视频生成模板（42 个建筑视频模板）
        from app.services.video_gen_service import seed_video_generation_templates

        seed_video_generation_templates(db)

        from app.services.ai_configuration import load_runtime_config

        load_runtime_config(db)
    except Exception as exc:
        logger.exception("seed_failed", error=str(exc))
    finally:
        db.close()


def _cleanup_stale_uploads() -> None:
    """启动时清理废弃的分片上传暂存目录，避免大文件残片写满磁盘。"""
    try:
        from app.services.upload_cleanup import cleanup_resumable_uploads

        cleanup_resumable_uploads()
    except Exception as exc:  # pragma: no cover
        logger.exception("upload_cleanup_failed", error=str(exc))


def _recover_local_tasks() -> None:
    try:
        from app.services.task_runner import recover_local_narration_tasks

        recover_local_narration_tasks()
    except Exception as exc:  # pragma: no cover
        logger.exception("local_task_recovery_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("fastvideo_start", env=settings.app_env, db=settings.database_url)
    _init_db()
    _cleanup_stale_uploads()
    _recover_local_tasks()
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

# 允许任意来源访问 API。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    admin,
    assets,
    auth,
    collaboration,
    concat,
    custom_segment,
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
    settings as settings_api,
    tasks,
    video,
    video_gen,
    voice,
    voices,
)

api_prefix = settings.api_v1_prefix
app.include_router(health.router, prefix=api_prefix)
app.include_router(auth.router, prefix=api_prefix)
app.include_router(admin.router, prefix=api_prefix)
app.include_router(projects.router, prefix=api_prefix)
app.include_router(collaboration.router, prefix=api_prefix)
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
app.include_router(concat.router, prefix=api_prefix)
app.include_router(custom_segment.router, prefix=api_prefix)
app.include_router(video_gen.router, prefix=api_prefix)
app.include_router(settings_api.router, prefix=api_prefix)
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
