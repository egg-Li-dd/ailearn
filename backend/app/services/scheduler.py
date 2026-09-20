"""任务调度器：每分钟驱动学习会话状态机并推送事件。

物理分库改造：遍历所有 active 用户，逐个用用户库执行状态推进和规划。
"""
import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from ..core.db import SessionLocal, user_db_manager, get_active_user_keys
from ..models import StudySession, Task
from ..models.enums import TaskStatus
from ..routers.ws import manager
from .planner import plan_today_pending
from .session_service import ensure_today_sessions, session_time_range, target_status
from .task_auto_progress import check_and_auto_progress

logger = logging.getLogger("ailearn.scheduler")

TICK_INTERVAL_SECONDS = 60


class TikResult:
    def __init__(self, session_id: int, old: str, new: str, user_key: str = "") -> None:
        self.session_id = session_id
        self.old = old
        self.new = new
        self.user_key = user_key


async def tick_once() -> list[TikResult]:
    """一次状态推进；返回发生的变更列表（供测试与广播）。"""
    changes = []
    try:
        loop = asyncio.get_running_loop()
        changes = await loop.run_in_executor(None, _tick_sync)
        for ch in changes:
            try:
                await manager.broadcast(
                    {
                        "type": "session_status_changed",
                        "session_id": ch.session_id,
                        "old_status": ch.old,
                        "status": ch.new,
                        "user_key": ch.user_key,
                    }
                )
            except Exception:
                logger.exception("broadcast session_status failed")
    except Exception:
        logger.exception("tick_once failed")

    # 课前任务补齐：进入 pre_class/in_class 且空任务的会话自动生成任务清单。
    # 放后台任务执行，避免 LLM 超时阻塞状态机扫描。
    _safe_create_task(_plan_background(), "plan_background")
    # 任务自动推进：检查学习中的任务，在截止前自动生成测试题，逾期标记
    _safe_create_task(check_and_auto_progress(), "check_and_auto_progress")
    return changes


def _safe_create_task(coro, name: str) -> None:
    """安全创建后台任务，捕获未处理异常防止进程崩溃。"""
    task = asyncio.create_task(coro)
    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception("background task %s crashed: %s", name, exc)
    task.add_done_callback(_on_done)


async def _plan_background() -> None:
    """遍历所有 active 用户，逐个用用户库执行会话规划。"""
    user_keys = get_active_user_keys()
    for user_key in user_keys:
        try:
            db = user_db_manager.get_session(user_key)
            try:
                planned = await plan_today_pending(db)
                for p in planned:
                    try:
                        await manager.broadcast(
                            {
                                "type": "session_planned",
                                "session_id": p["session_id"],
                                "task_count": len(p["tasks"]),
                                "user_key": user_key,
                            }
                        )
                    except Exception:
                        logger.exception("broadcast session_planned failed for user=%s", user_key)
            finally:
                db.close()
        except Exception:
            logger.exception("plan_background failed for user=%s", user_key)


def _tick_sync() -> list[TikResult]:
    """遍历所有 active 用户，逐个用用户库执行状态推进。"""
    changes: list[TikResult] = []
    user_keys = get_active_user_keys()
    for user_key in user_keys:
        try:
            user_changes = _tick_for_user(user_key)
            changes.extend(user_changes)
        except Exception:
            logger.exception("tick failed for user=%s", user_key)
    return changes


def _tick_for_user(user_key: str) -> list[TikResult]:
    """对单个用户执行状态推进。"""
    changes: list[TikResult] = []
    db = user_db_manager.get_session(user_key)
    try:
        now = datetime.now()  # 本地时间驱动状态机
        sessions = ensure_today_sessions(db)
        for session in sessions:
            rng = session_time_range(db, session)
            if rng is None:
                continue
            start, end = rng
            has_unfinished = db.scalar(
                select(Task.id)
                .where(Task.session_id == session.id, Task.status != TaskStatus.DONE)
                .limit(1)
            ) is not None
            wanted = target_status(now, start, end, has_unfinished_tasks=bool(has_unfinished))
            if session.status != wanted:
                old = session.status
                session.status = wanted
                db.commit()
                changes.append(TikResult(session.id, old, wanted, user_key))
                logger.info("user=%s session %d: %s -> %s", user_key, session.id, old, wanted)
    finally:
        db.close()
    return changes


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        tick_once,
        "interval",
        seconds=TICK_INTERVAL_SECONDS,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("scheduler started (every %ds)", TICK_INTERVAL_SECONDS)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
