"""数据库引擎与会话。

物理分库设计：
- 全局库 ailearn.db：users, ai_channels, ai_call_logs, system_logs 等共享资源
- 用户库 users/{db_key}.db：courses, knowledge, tasks, quiz 等业务数据
"""
from datetime import datetime, timezone
from threading import Lock

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from .config import SQLALCHEMY_DATABASE_URL, USER_DB_DIR


def utcnow() -> datetime:
    """统一 UTC 时间（存储用），读取侧转本地。"""
    return datetime.now(timezone.utc)


# ========== 全局库 ==========
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


# SQLite 性能优化：WAL 模式 + 外键约束 + 合理缓存
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA cache_size=-20000")  # 20MB 缓存
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ========== 用户库表清单（物理分库时只创建这些表） ==========
USER_DB_TABLE_NAMES = {
    # 科目与课表
    "courses", "schedule_items", "schedule_exceptions", "schedule_templates",
    # 知识体系
    "knowledge_nodes", "mastery_records", "review_queue", "course_memories",
    # 对话与课堂
    "conversations", "messages", "sediment_suggestions",
    # 学习会话与任务
    "study_sessions", "tasks", "task_events",
    # 测验
    "quiz_questions", "quiz_sessions", "quiz_session_items", "quiz_answers",
    # 用户级设置
    "user_settings",
}


class UserDbManager:
    """用户库引擎管理器（单例）。

    每个用户一个独立的 SQLite 文件，独立 engine，写锁不竞争。
    首次访问时自动建库 + 建业务表。
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._engines = {}
                    cls._instance._sessionmakers = {}
        return cls._instance

    def _db_path(self, db_key: str) -> str:
        return str(USER_DB_DIR / f"{db_key}.db")

    def get_engine(self, db_key: str):
        """获取用户库 engine，已缓存直接返回，未缓存则创建并建表。"""
        if db_key not in self._engines:
            with self._lock:
                if db_key not in self._engines:
                    eng = create_engine(
                        f"sqlite:///{self._db_path(db_key)}",
                        connect_args={"check_same_thread": False},
                        pool_pre_ping=True,
                    )

                    # SQLite 性能优化
                    @event.listens_for(eng, "connect")
                    def _set_user_sqlite_pragma(dbapi_connection, connection_record):
                        cursor = dbapi_connection.cursor()
                        cursor.execute("PRAGMA journal_mode=WAL")
                        cursor.execute("PRAGMA foreign_keys=ON")
                        cursor.execute("PRAGMA cache_size=-10000")
                        cursor.execute("PRAGMA synchronous=NORMAL")
                        cursor.close()

                    # 只创建业务表，不创建全局表
                    from app import models  # noqa: F401
                    tables_to_create = [
                        t for name, t in Base.metadata.tables.items()
                        if name in USER_DB_TABLE_NAMES
                    ]
                    Base.metadata.create_all(bind=eng, tables=tables_to_create)

                    self._engines[db_key] = eng
                    self._sessionmakers[db_key] = sessionmaker(
                        bind=eng, autoflush=False, expire_on_commit=False
                    )
        return self._engines[db_key]

    def get_session(self, db_key: str) -> Session:
        """创建用户库 session。"""
        self.get_engine(db_key)
        return self._sessionmakers[db_key]()

    def close_all(self):
        """关闭所有用户库 engine（应用关闭时调用）。"""
        with self._lock:
            for eng in self._engines.values():
                eng.dispose()
            self._engines.clear()
            self._sessionmakers.clear()


# 全局单例
user_db_manager = UserDbManager()


# ========== 初始化与依赖注入 ==========

def init_db() -> None:
    """建全局库表（M0 使用 create_all，Alembic 迁移后置）。"""
    from app import models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(bind=engine)


def get_global_db():
    """全局库 session 依赖（users, ai_channels, system_logs 等）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_db():
    """用户库 session 依赖（courses, knowledge, tasks 等业务数据）。

    必须在 UserResolverMiddleware 之后使用，从 request.state 获取 db_key。
    """
    from fastapi import Request, HTTPException
    # 这里通过 context 方式获取，实际在路由中通过 Depends 注入
    # 由于 FastAPI 依赖注入无法直接访问 request.state，
    # 我们在路由函数中显式传入 db_key，或使用 middleware 设置 contextvar
    raise HTTPException(
        status_code=500,
        detail="get_user_db() 不能直接作为依赖使用，请用 get_user_db_for_key(db_key)"
    )


def get_user_db_for_key(db_key: str):
    """返回一个用户库 session 生成器（用于路由中显式调用）。"""
    db = user_db_manager.get_session(db_key)
    try:
        yield db
    finally:
        db.close()


def get_db(request: Request):
    """智能 DB 路由依赖（向后兼容入口）。

    根据 request.state.user_db_key 自动选择：
    - 有用户上下文 → 返回对应用户库 session
    - 无用户上下文（公开路径/管理台全局操作）→ 返回全局库 session

    所有现有业务路由使用 Depends(get_db) 即可自动路由到用户库，
    无需逐个修改。需要明确使用全局库时用 Depends(get_global_db)。
    """
    db_key = getattr(request.state, "user_db_key", None)
    if db_key:
        db = user_db_manager.get_session(db_key)
    else:
        db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_active_user_keys() -> list[str]:
    """从全局库查询所有 active 用户的 db_key 列表（用于后台任务遍历）。

    物理分库后，scheduler/planner 等后台任务需要逐个用户执行，
    此函数提供需要遍历的用户库 key 列表。
    """
    from sqlalchemy import select
    from ..models.user import User
    db = SessionLocal()
    try:
        keys = db.scalars(
            select(User.db_key)
            .where(User.is_active == True, User.db_key.isnot(None))
        ).all()
        return [k for k in keys if k]
    finally:
        db.close()
