"""统一异常处理。

定义业务异常基类，并注册 FastAPI 全局异常处理器，
使前端始终收到一致的 JSON 错误结构：

    {"code": "XXX", "message": "中文描述", "detail": {...}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """业务异常基类。"""

    status_code = 400
    code = "APP_ERROR"

    def __init__(
        self,
        message: str = "请求处理失败",
        *,
        detail: dict[str, Any] | None = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class AIProviderError(AppError):
    """AI 服务调用失败（可用于重试）。"""

    status_code = 502
    code = "AI_PROVIDER_ERROR"


def _error_body(status_code: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.warning("app_error", path=request.url.path, code=exc.code, message=exc.message)
        return _error_body(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        logger.warning("validation_error", path=request.url.path, errors=exc.errors())
        return _error_body(
            422,
            "VALIDATION_ERROR",
            "请求参数校验失败",
            {"errors": exc.errors()},
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error_handler(request: Request, exc: SQLAlchemyError):
        logger.exception("db_error", path=request.url.path)
        return _error_body(500, "DATABASE_ERROR", "数据库操作失败，请稍后重试")

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("unhandled_error", path=request.url.path)
        return _error_body(500, "INTERNAL_ERROR", "服务器内部错误")
