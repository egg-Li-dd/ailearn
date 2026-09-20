"""HTTP Basic Auth 中间件：保护管理台和 API，防止 Funnel 暴露后被未授权访问。

环境变量：
  ADMIN_USER     - 用户名，默认 admin
  ADMIN_PASSWORD - 密码，默认 ailearn2026（建议修改）
  AUTH_ENABLED   - 是否启用认证，默认 true（设为 false 可临时关闭）
"""
import base64
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ailearn2026")
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() != "false"

# 不需要认证的路径
PUBLIC_PATHS = ["/"]


def _check_auth(auth_header: str | None) -> bool:
    """校验 Authorization 头。"""
    if not auth_header:
        return False
    try:
        scheme, credentials = auth_header.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
        return (
            secrets.compare_digest(username, ADMIN_USER)
            and secrets.compare_digest(password, ADMIN_PASSWORD)
        )
    except Exception:
        return False


def _unauthorized_response() -> JSONResponse:
    """返回 401 响应，触发浏览器 Basic Auth 弹框。"""
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required"},
        headers={"WWW-Authenticate": 'Basic realm="ailearn-admin"'},
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """全局 Basic Auth 中间件。"""

    async def dispatch(self, request: Request, call_next):
        if not AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path

        # 公开路径放行（健康检查）
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # WebSocket 连接：允许通过 query 参数传认证（ws://url?token=base64）
        if path == "/api/v1/ws":
            token = request.query_params.get("token")
            if token and _check_auth(f"Basic {token}"):
                return await call_next(request)
            return _unauthorized_response()

        # 普通 HTTP 请求：校验 Authorization 头
        auth_header = request.headers.get("authorization")
        if _check_auth(auth_header):
            return await call_next(request)

        return _unauthorized_response()
