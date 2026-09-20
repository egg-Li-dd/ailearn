"""数据库日志 Handler：将 WARNING 及以上日志写入 system_logs 表并推送 WS。

特点：
1. 异步写入，不阻塞业务线程
2. 自动关联当前后台任务 ID（通过 contextvars）
3. 异常堆栈自动提取到 detail 字段
4. 批量写入，减少 DB 压力
"""
import asyncio
import logging
import traceback
from datetime import datetime

from .db import SessionLocal
from ..models import SystemLog
from ..services.task_center import current_task_id

# 异步写入队列
_log_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None
_worker_started = False

# 模块名映射：从 logger name 提取业务模块
_MODULE_MAP = {
    "ailearn.scheduler": "scheduler",
    "ailearn.task_auto_progress": "scheduler",
    "ailearn.ai_gateway": "ai_gateway",
    "ailearn.call_logger": "ai_call",
    "ailearn.ai_action": "ai_action",
    "ailearn.task_center": "task_center",
    "ailearn.background_task": "task_center",
    "ailearn.classroom": "classroom",
    "ailearn.planner": "planner",
    "ailearn.quiz": "quiz",
    "ailearn.review": "review",
    "ailearn.knowledge": "knowledge",
    "ailearn.session": "session",
    "ailearn.chat": "chat",
    "ailearn.asr": "asr",
    "ailearn.stats": "stats",
    "ailearn.audit": "audit",
    "ailearn.migrate": "migration",
    "ailearn.main": "system",
    "ailearn.ws": "websocket",
}


def _extract_module(logger_name: str) -> str:
    """从 logger 名提取业务模块。"""
    for prefix, module in _MODULE_MAP.items():
        if logger_name.startswith(prefix):
            return module
    # 尝试从 ailearn.xxx 提取
    if logger_name.startswith("ailearn."):
        parts = logger_name.split(".")
        if len(parts) >= 2:
            return parts[1]
    return "system"


class DatabaseLogHandler(logging.Handler):
    """将日志写入 SQLite 的 Handler（异步队列方式）。"""

    def __init__(self, level: int = logging.WARNING):
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord):
        try:
            # 提取异常堆栈
            detail = ""
            if record.exc_info:
                detail = "".join(traceback.format_exception(*record.exc_info))

            # 关联任务 ID
            task_id = current_task_id()

            log_entry = {
                "level": record.levelname,
                "logger_name": record.name,
                "message": self.format(record) if self.formatter else record.getMessage(),
                "module": _extract_module(record.name),
                "detail": detail[:4000] if detail else "",
                "task_id": task_id,
                "created_at": datetime.utcnow(),
            }

            # 尝试入队（异步）
            if _log_queue is not None:
                try:
                    _log_queue.put_nowait(log_entry)
                except asyncio.QueueFull:
                    pass  # 队列满时丢弃，避免阻塞
            else:
                # 队列未初始化（启动前），直接同步写入
                _write_logs([log_entry])

            # 推送 WS（ERROR 及以上实时推送）
            if record.levelno >= logging.ERROR:
                _push_log_ws(log_entry)

        except Exception:
            # Handler 内部异常绝不能影响业务
            pass


def _write_logs(logs: list[dict]) -> None:
    """批量写入日志到 DB。"""
    if not logs:
        return
    db = SessionLocal()
    try:
        entries = [
            SystemLog(
                level=log["level"],
                logger_name=log["logger_name"],
                message=log["message"][:2000],
                module=log["module"],
                detail=log["detail"],
                task_id=log["task_id"],
                created_at=log["created_at"],
            )
            for log in logs
        ]
        db.add_all(entries)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _push_log_ws(log_entry: dict) -> None:
    """推送日志到 WebSocket（ERROR+ 实时推送）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无运行中的事件循环，跳过
    try:
        from ..routers.ws import manager
        event = {
            "type": "log_entry",
            "level": log_entry["level"],
            "logger_name": log_entry["logger_name"],
            "module": log_entry["module"],
            "message": log_entry["message"][:500],
            "task_id": log_entry["task_id"],
            "created_at": log_entry["created_at"].isoformat(),
        }
        loop.create_task(manager.broadcast(event))
    except Exception:
        pass


async def _log_worker():
    """后台日志写入协程：批量消费队列。"""
    batch = []
    last_flush = asyncio.get_event_loop().time()
    while True:
        try:
            # 等待第一条日志或超时
            try:
                entry = await asyncio.wait_for(_log_queue.get(), timeout=1.0)
                batch.append(entry)
            except asyncio.TimeoutError:
                pass

            # 批量收集（最多 50 条或 1 秒）
            while len(batch) < 50:
                try:
                    entry = _log_queue.get_nowait()
                    batch.append(entry)
                except asyncio.QueueEmpty:
                    break

            now = asyncio.get_event_loop().time()
            if batch and (len(batch) >= 10 or now - last_flush >= 1.0):
                _write_logs(batch)
                batch.clear()
                last_flush = now
        except asyncio.CancelledError:
            # 退出前刷新剩余
            if batch:
                _write_logs(batch)
            break
        except Exception:
            # Worker 异常不中断
            await asyncio.sleep(1)


def start_log_worker() -> None:
    """启动日志写入协程（在 FastAPI lifespan 中调用）。"""
    global _log_queue, _worker_task, _worker_started
    if _worker_started:
        return
    _log_queue = asyncio.Queue(maxsize=1000)
    _worker_task = asyncio.create_task(_log_worker())
    _worker_started = True
    logging.getLogger("ailearn").info("数据库日志 Handler 已启动（WARNING+ 写入 DB）")


def stop_log_worker() -> None:
    """停止日志写入协程。"""
    global _worker_task, _worker_started
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_started = False
