"""统一日志配置：控制台 + 文件轮转 + DB（WARNING+），按模块分级。"""
import logging
import logging.handlers
from pathlib import Path

from .config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(level: int = logging.INFO) -> None:
    """初始化全局日志（幂等）。"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加 handler
    if root.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    # 控制台
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    # 文件（按天轮转，保留 14 天）
    log_file = LOG_DIR / "ailearn.log"
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    # DB Handler（WARNING 及以上写入 system_logs 表，异步队列）
    try:
        from .logging_handler import DatabaseLogHandler
        db_handler = DatabaseLogHandler(level=logging.WARNING)
        db_handler.setFormatter(formatter)
        root.addHandler(db_handler)
    except Exception:
        # DB Handler 初始化失败不影响主流程
        pass

    # 降低第三方库日志噪音
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
