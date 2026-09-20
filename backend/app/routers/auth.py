"""认证路由：注册 / 登录 / 探活 / 用户管理。"""
import re
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_global_db, user_db_manager
from ..core.security import hash_pin, hash_token, new_token, verify_pin
from ..models import User
from ..schemas.auth import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPinRequest,
    UserCreate,
    UserOut,
    UserUpdate,
)

logger = logging.getLogger("ailearn.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def _issue_token(db: Session, user: User) -> str:
    raw, hashed = new_token()
    user.token_hash = hashed
    db.commit()
    return raw


def _validate_pin(pin: str) -> None:
    if not pin.isdigit():
        raise HTTPException(status_code=422, detail="PIN 必须为 4-6 位数字")
    if not 4 <= len(pin) <= 6:
        raise HTTPException(status_code=422, detail="PIN 必须为 4-6 位数字")


def _generate_db_key(username: str, db: Session) -> str:
    """从用户名生成 db_key，冲突时加序号。"""
    # 只保留字母数字和下划线，转小写
    base = re.sub(r"[^a-zA-Z0-9_]", "", username).lower()
    if not base:
        base = "user"
    # 截断到 28 位（留 4 位给序号）
    base = base[:28]

    candidate = base
    suffix = 1
    while db.scalar(select(User).where(User.db_key == candidate)):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def _init_user_database(user: User) -> None:
    """初始化用户业务库（建库 + 建表）。"""
    user_db_manager.get_engine(user.db_key)
    logger.info("用户 %s 的业务库已初始化: %s.db", user.username, user.db_key)


# ========== 注册 / 登录 ==========

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_global_db)):
    """用户注册：username + nickname + PIN，自动初始化用户业务库。"""
    _validate_pin(payload.pin)

    # 检查用户名唯一
    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists:
        raise HTTPException(status_code=409, detail="用户名已被注册")

    # 生成 db_key
    db_key = _generate_db_key(payload.username, db)

    user = User(
        username=payload.username,
        nickname=payload.nickname,
        pin_hash=hash_pin(payload.pin),
        db_key=db_key,
        device_id=payload.device_id,
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 初始化用户业务库
    _init_user_database(user)

    token = _issue_token(db, user)
    logger.info("用户注册成功: %s (db_key=%s)", user.username, user.db_key)

    return AuthResponse(
        user_id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        token=token,
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_global_db)):
    """用户登录：username + PIN。"""
    _validate_pin(payload.pin)
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_pin(payload.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="用户名或 PIN 错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 更新最后登录时间
    from ..core.db import utcnow
    user.last_login_at = utcnow()
    db.commit()

    token = _issue_token(db, user)
    logger.info("用户登录: %s", user.username)

    return AuthResponse(
        user_id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        token=token,
    )


@router.get("/me", response_model=MeResponse)
def me(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_global_db),
):
    """获取当前登录用户信息。"""
    if not credentials:
        raise HTTPException(status_code=401, detail="未提供 token")
    user = db.scalar(select(User).where(User.token_hash == hash_token(credentials.credentials)))
    if not user:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    return MeResponse(
        user_id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        db_key=user.db_key,
        device_id=user.device_id,
        created_at=user.created_at.isoformat() if user.created_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


# ========== 管理台：用户管理（仅 admin） ==========

def _require_admin(request: Request) -> None:
    """校验当前用户是否为 admin。

    管理台通过 HTTP Basic Auth 认证（全局管理员），切换到 admin 用户时也通过。
    App 端通过 Bearer token 认证，需要 role=admin。
    """
    if not request.state.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")


@router.get("/admin/users", response_model=list[UserOut], tags=["admin-users"])
def admin_list_users(
    request: Request,
    db: Session = Depends(get_global_db),
):
    """管理台：获取所有用户列表。"""
    _require_admin(request)
    users = db.scalars(select(User).order_by(User.id)).all()
    return [
        UserOut(
            id=u.id,
            username=u.username,
            nickname=u.nickname,
            role=u.role,
            db_key=u.db_key,
            device_id=u.device_id,
            is_active=u.is_active,
            created_at=u.created_at.isoformat() if u.created_at else None,
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
        )
        for u in users
    ]


@router.post("/admin/users", response_model=UserOut, status_code=201, tags=["admin-users"])
def admin_create_user(
    request: Request,
    payload: UserCreate,
    db: Session = Depends(get_global_db),
):
    """管理台：创建用户（可指定 role）。"""
    _require_admin(request)
    _validate_pin(payload.pin)

    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists:
        raise HTTPException(status_code=409, detail="用户名已被注册")

    if payload.role not in ("admin", "user"):
        raise HTTPException(status_code=422, detail="role 必须是 admin 或 user")

    db_key = _generate_db_key(payload.username, db)

    user = User(
        username=payload.username,
        nickname=payload.nickname,
        pin_hash=hash_pin(payload.pin),
        db_key=db_key,
        device_id=payload.device_id,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _init_user_database(user)
    logger.info("管理员创建用户: %s (role=%s)", user.username, user.role)

    return UserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        db_key=user.db_key,
        device_id=user.device_id,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


@router.put("/admin/users/{user_id}", response_model=UserOut, tags=["admin-users"])
def admin_update_user(
    request: Request,
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_global_db),
):
    """管理台：修改用户信息（昵称/角色/启用状态）。"""
    _require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if payload.nickname is not None:
        user.nickname = payload.nickname
    if payload.role is not None:
        if payload.role not in ("admin", "user"):
            raise HTTPException(status_code=422, detail="role 必须是 admin 或 user")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    logger.info("管理员更新用户: %s", user.username)

    return UserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        db_key=user.db_key,
        device_id=user.device_id,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


@router.post("/admin/users/{user_id}/reset-pin", tags=["admin-users"])
def admin_reset_pin(
    request: Request,
    user_id: int,
    payload: ResetPinRequest,
    db: Session = Depends(get_global_db),
):
    """管理台：重置用户 PIN。"""
    _require_admin(request)
    _validate_pin(payload.pin)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.pin_hash = hash_pin(payload.pin)
    user.token_hash = None  # 使现有 token 失效
    db.commit()
    logger.info("管理员重置用户 PIN: %s", user.username)
    return {"detail": "PIN 已重置，原有登录态已失效"}


@router.delete("/admin/users/{user_id}", tags=["admin-users"])
def admin_delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_global_db),
):
    """管理台：删除用户（同时删除用户业务库文件）。"""
    _require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不能删除自己
    if user.id == request.state.operator_user_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")

    db_key = user.db_key
    username = user.username

    db.delete(user)
    db.commit()

    # 删除用户业务库文件
    import os
    from ..core.config import USER_DB_DIR
    for ext in ("", "-wal", "-shm"):
        fpath = USER_DB_DIR / f"{db_key}.db{ext}"
        if fpath.exists():
            try:
                os.remove(fpath)
            except OSError as e:
                logger.warning("删除用户库文件失败 %s: %s", fpath, e)

    logger.info("管理员删除用户: %s (db_key=%s)", username, db_key)
    return {"detail": f"用户 {username} 已删除"}


@router.get("/admin/users/{user_id}/stats", tags=["admin-users"])
def admin_user_stats(
    request: Request,
    user_id: int,
    db: Session = Depends(get_global_db),
):
    """管理台：获取用户数据统计（从用户业务库查询）。"""
    _require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user_db = user_db_manager.get_session(user.db_key)
    try:
        from sqlalchemy import text
        stats = {}
        # 统计表记录数
        for table in ["courses", "knowledge_nodes", "quiz_questions", "tasks",
                       "study_sessions", "quiz_sessions", "schedule_items",
                       "conversations", "messages"]:
            try:
                result = user_db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                stats[table] = result.scalar()
            except Exception:
                stats[table] = 0
        return stats
    finally:
        user_db.close()
