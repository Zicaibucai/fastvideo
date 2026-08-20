"""统一日志系统。

提供结构化日志（structlog）+ 标准库 fallback。所有业务模块通过
`logger = get_logger(__name__)` 获取 logger。
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


def _configure_std_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=level,
        stream=sys.stdout,
    )
    # 降低第三方库噪音
    for noisy in ("uvicorn.access", "httpx", "httpcore", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def setup_logging() -> None:
    _configure_std_logging()

    if settings.app_env == "production":
        processors: list = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or "fastvideo")


# 模块导入时即完成日志初始化
setup_logging()
