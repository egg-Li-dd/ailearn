"""全局异常处理：统一错误响应格式，避免堆栈泄露。"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("ailearn.exceptions")


class AppError(Exception):
    """应用层业务异常基类。"""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str = "资源冲突"):
        super().__init__(message, status_code=409)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器到 FastAPI 实例。"""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        logger.warning("ValueError: %s", exc)
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务内部错误，请稍后重试"},
        )
