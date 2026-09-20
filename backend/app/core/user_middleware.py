"""用户解析中间件。

从请求中识别当前用户，注入 request.state：
- request.state.user_id
- request.state.username
- request.state.nickname
- request.state.role
- request.state.user_db_key
- request.state.is_admin

用户识别优先级：
1. X-User-Key header（管理台切换查看，仅 admin 角色可用）
2. Authorization: Bearer <token>（App 端正常登录）
"""
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select

from .db import SessionLocal
from .security import hash_token
from .user_context import set_current_user_key, reset_current_user_key
from ..models import User

logger = logging.getLogger("ailearn.user_middleware")

# 不需要用户解析的路径
PUBLIC_PATHS = {"/", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}


class UserResolverMiddleware(BaseHTTPMiddleware):
    """解析当前用户并注入 request.state。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公开路径跳过
        if path in PUBLIC_PATHS:
            request.state.user_id = None
            request.state.username = None
            request.state.nickname = None
            request.state.role = None
            request.state.user_db_key = None
            request.state.is_admin = False
            return await call_next(request)

        db = SessionLocal()
        user_token = None
        try:
            user = None
            override_user = None

            # 1. 先从 token 解析当前登录用户（用于权限校验）
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1]
                token_hash = hash_token(token)
                user = db.scalar(select(User).where(User.token_hash == token_hash))

            # 2. 管理台切换查看：X-User-Key header
            # 管理台通过 HTTP Basic Auth 认证（全局管理员），带 X-User-Key 时直接切换
            # App 端通过 Bearer token 认证，X-User-Key 只有 admin 角色才能用
            x_user_key = request.headers.get("x-user-key")
            is_basic_auth = auth_header and auth_header.lower().startswith("basic ")

            if x_user_key:
                can_override = False
                if is_basic_auth:
                    # 管理台 Basic Auth 已通过全局认证，允许切换
                    can_override = True
                elif user and user.is_admin:
                    # App 端 admin 角色也允许切换
                    can_override = True

                if can_override:
                    override_user = db.scalar(
                        select(User).where(User.db_key == x_user_key)
                    )
                    if override_user:
                        logger.debug(
                            "切换查看用户: %s (operator=%s)",
                            override_user.username,
                            user.username if user else "admin(basic)",
                        )
                elif not is_basic_auth and not user:
                    logger.debug("X-User-Key present but no auth, path=%s", path)

            # 最终生效的用户：优先切换查看的用户，否则登录用户
            effective_user = override_user or user

            if effective_user and effective_user.is_active:
                request.state.user_id = effective_user.id
                request.state.username = effective_user.username
                request.state.nickname = effective_user.nickname
                request.state.role = effective_user.role
                request.state.user_db_key = effective_user.db_key
                # Basic Auth 管理台始终是管理员（即使切换查看普通用户）
                request.state.is_admin = effective_user.is_admin or is_basic_auth
                # 记录实际操作者（用于审计）
                request.state.operator_user_id = user.id if user else None
                # 设置 contextvar，供 ai_gateway 等服务读取
                user_token = set_current_user_key(effective_user.db_key)
            else:
                request.state.user_id = None
                request.state.username = None
                request.state.nickname = None
                request.state.role = None
                request.state.user_db_key = None
                # 管理台 Basic Auth 视为全局管理员
                request.state.is_admin = is_basic_auth
                request.state.operator_user_id = None
                user_token = set_current_user_key(None)

        except Exception as e:
            logger.warning("用户解析失败: %s", e, exc_info=True)
            request.state.user_id = None
            request.state.username = None
            request.state.nickname = None
            request.state.role = None
            request.state.user_db_key = None
            request.state.is_admin = locals().get('is_basic_auth', False)
            request.state.operator_user_id = None
            user_token = set_current_user_key(None)
        finally:
            db.close()

        try:
            return await call_next(request)
        finally:
            # 请求结束后重置 contextvar
            try:
                reset_current_user_key(user_token)
            except Exception:
                pass
