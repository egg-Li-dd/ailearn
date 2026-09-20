"""当前用户上下文（contextvars）。

用于在异步调用链中传递当前用户的 user_key，避免逐层传参。
由 UserResolverMiddleware 设置，ai_gateway 等服务读取。
"""
import contextvars

# 当前用户的 db_key（None 表示未登录/全局）
_current_user_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_key", default=None
)


def set_current_user_key(user_key: str | None) -> contextvars.Token:
    """设置当前用户 key，返回 token 用于恢复。"""
    return _current_user_key.set(user_key)


def get_current_user_key() -> str | None:
    """获取当前用户 key。"""
    return _current_user_key.get()


def reset_current_user_key(token: contextvars.Token) -> None:
    """恢复之前的用户 key。"""
    _current_user_key.reset(token)
