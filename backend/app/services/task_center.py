"""统一后台任务中心：注册、进度更新、状态管理、取消、查询。

设计原则：
1. DB 持久化 + 内存缓存双写，刷新页面不丢失
2. 协作式取消：设置 cancelled 标志，任务函数定期检查 is_cancelled()
3. 进度更新防抖：500ms 内多次更新只推送最后一次 WS，DB 事件全量记录
4. 与日志关联：任务执行期间的系统日志自动带 task_id
"""
import asyncio
import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import BackgroundTask, TaskEvent

logger = logging.getLogger("ailearn.task_center")

# 上下文变量：当前执行的任务 ID（装饰器自动设置）
_current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)

# 取消标志集合（内存）
_cancelled: set[str] = set()

# 进度防抖：task_id -> (last_push_time, last_progress, last_stage)
_push_throttle: dict[str, tuple[float, int, str]] = {}

# 任务执行函数注册表（用于重试）
_runners: dict[str, Callable[..., Coroutine]] = {}

PUSH_THROTTLE_MS = 500


def current_task_id() -> str | None:
    """获取当前上下文中的任务 ID（在被 @background_task 装饰的函数内调用）。"""
    return _current_task_id.get()


def is_cancelled(task_id: str | None = None) -> bool:
    """检查任务是否被取消。任务函数应在每个步骤间调用。"""
    tid = task_id or _current_task_id.get()
    if not tid:
        return False
    return tid in _cancelled


def register_runner(task_type: str, func: Callable[..., Coroutine]) -> None:
    """注册任务类型对应的执行函数（用于重试时重新启动）。"""
    _runners[task_type] = func


def create_task(
    task_type: str,
    title: str,
    metadata: dict | None = None,
    total_steps: int = 0,
    user_key: str | None = None,
) -> str:
    """创建后台任务，返回 task_id。立即写入 DB + 记录事件。

    Args:
        task_type: 任务类型标识
        title: 任务标题（展示用）
        metadata: 关联数据（如 node_id, session_id），JSON 存储
        total_steps: 总步骤数（用于分步进度）
        user_key: 物理分库后任务归属用户的 db_key，None 表示全局任务

    Returns:
        task_id (uuid hex)
    """
    task_id = uuid.uuid4().hex
    db = SessionLocal()
    try:
        task = BackgroundTask(
            id=task_id,
            task_type=task_type,
            title=title,
            status="pending",
            progress=0,
            total_steps=total_steps,
            metadata_=json.dumps(metadata or {}, ensure_ascii=False),
            user_key=user_key,
        )
        db.add(task)
        db.commit()
        _add_event(db, task_id, "created", f"任务创建：{title}")
        logger.info("任务创建: id=%s type=%s title=%s user=%s", task_id, task_type, title, user_key)
    finally:
        db.close()

    # 异步推送 WS（不阻塞）
    _safe_broadcast({
        "type": "task_created",
        "task_id": task_id,
        "task_type": task_type,
        "title": title,
        "status": "pending",
        "progress": 0,
        "user_key": user_key,
    })
    return task_id


def update_progress(
    task_id: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
    message: str = "",
    current_step: int | None = None,
) -> None:
    """更新任务进度。写入 task_events + 防抖推送 WS。

    Args:
        task_id: 任务 ID，默认取当前上下文
        progress: 0-100，None 表示不更新
        stage: 当前阶段描述
        message: 事件消息
        current_step: 当前步骤序号
    """
    tid = task_id or _current_task_id.get()
    if not tid:
        return

    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, tid)
        if not task:
            return
        if task.status in ("completed", "failed", "cancelled"):
            return

        changed = False
        if progress is not None:
            progress = max(0, min(100, int(progress)))
            if progress != task.progress:
                task.progress = progress
                changed = True
        if stage is not None:
            if stage != task.stage:
                task.stage = stage
                changed = True
        if current_step is not None:
            task.current_step = current_step
            changed = True

        if changed:
            db.commit()

        _add_event(
            db, tid, "progress",
            message or stage or f"进度 {task.progress}%",
            progress=task.progress,
        )
    finally:
        db.close()

    # 防抖推送 WS
    _throttled_push(tid, progress, stage)


def log_message(task_id: str | None = None, message: str = "") -> None:
    """记录任务日志事件（不更新进度）。"""
    tid = task_id or _current_task_id.get()
    if not tid:
        return
    db = SessionLocal()
    try:
        _add_event(db, tid, "log", message)
    finally:
        db.close()


def complete_task(task_id: str | None = None, result: dict | None = None) -> None:
    """标记任务完成。"""
    tid = task_id or _current_task_id.get()
    if not tid:
        return

    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, tid)
        if not task:
            return
        task.status = "completed"
        task.progress = 100
        task.finished_at = datetime.utcnow()
        if result is not None:
            task.result = json.dumps(result, ensure_ascii=False)
        db.commit()
        _add_event(db, tid, "completed", "任务完成", progress=100)
        logger.info("任务完成: id=%s type=%s", tid, task.task_type)
    finally:
        db.close()

    _cancelled.discard(tid)
    _push_throttle.pop(tid, None)
    _safe_broadcast({
        "type": "task_completed",
        "task_id": tid,
        "result": result or {},
    })


def fail_task(task_id: str | None = None, error: str = "") -> None:
    """标记任务失败。"""
    tid = task_id or _current_task_id.get()
    if not tid:
        return

    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, tid)
        if not task:
            return
        task.status = "failed"
        task.error = error[:2000]
        task.finished_at = datetime.utcnow()
        db.commit()
        _add_event(db, tid, "failed", f"任务失败：{error}", progress=task.progress)
        logger.error("任务失败: id=%s type=%s error=%s", tid, task.task_type, error)
    finally:
        db.close()

    _cancelled.discard(tid)
    _push_throttle.pop(tid, None)
    _safe_broadcast({
        "type": "task_failed",
        "task_id": tid,
        "error": error,
    })


def cancel_task(task_id: str) -> bool:
    """取消任务（协作式）。设置取消标志，任务函数检查后自行退出。

    Returns:
        True 表示成功发出取消请求；False 表示任务不存在或已结束
    """
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if not task:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            return False
        if task.status == "pending":
            # pending 状态直接标记取消
            task.status = "cancelled"
            task.finished_at = datetime.utcnow()
            db.commit()
            _add_event(db, task_id, "cancelled", "任务已取消（未开始）")
            _push_throttle.pop(task_id, None)
            _safe_broadcast({"type": "task_cancelled", "task_id": task_id})
            return True
        # running 状态设置标志，等任务函数自行检查
        _cancelled.add(task_id)
        _add_event(db, task_id, "cancelled", "取消请求已发出，等待当前步骤结束")
        _safe_broadcast({"type": "task_cancel_requested", "task_id": task_id})
        return True
    finally:
        db.close()


def mark_running(task_id: str) -> None:
    """标记任务开始运行（装饰器内部调用）。"""
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        _add_event(db, task_id, "started", "任务开始执行")
        logger.info("任务开始: id=%s type=%s", task_id, task.task_type)
    finally:
        db.close()

    _safe_broadcast({
        "type": "task_started",
        "task_id": task_id,
    })


def mark_cancelled(task_id: str) -> None:
    """任务函数检测到取消标志后，调用此方法正式标记取消。"""
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if not task:
            return
        task.status = "cancelled"
        task.finished_at = datetime.utcnow()
        db.commit()
        _add_event(db, task_id, "cancelled", "任务已取消", progress=task.progress)
        logger.info("任务取消: id=%s type=%s progress=%d", task_id, task.task_type, task.progress)
    finally:
        db.close()

    _cancelled.discard(task_id)
    _push_throttle.pop(task_id, None)
    _safe_broadcast({"type": "task_cancelled", "task_id": task_id})


def get_task(task_id: str) -> dict | None:
    """查询单个任务详情（含 metadata 解析）。"""
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if not task:
            return None
        return _task_to_dict(task)
    finally:
        db.close()


def list_tasks(status: str | None = None, limit: int = 50, user_key: str | None = None) -> list[dict]:
    """查询任务列表。进行中优先，最近完成次之。

    Args:
        status: 按状态过滤，None 表示全部
        limit: 返回数量上限
        user_key: 物理分库后按用户过滤，None 表示全部（管理台用）
    """
    db = SessionLocal()
    try:
        stmt = select(BackgroundTask)
        if status:
            stmt = stmt.where(BackgroundTask.status == status)
        if user_key:
            stmt = stmt.where(BackgroundTask.user_key == user_key)
        stmt = stmt.order_by(
            # 进行中排最前，然后按创建时间倒序
            BackgroundTask.status.in_(["running", "pending"]).desc(),
            BackgroundTask.created_at.desc(),
        ).limit(limit)
        tasks = list(db.scalars(stmt))
        return [_task_to_dict(t) for t in tasks]
    finally:
        db.close()


def list_active_tasks() -> list[dict]:
    """查询所有进行中的任务（running + pending）。"""
    db = SessionLocal()
    try:
        stmt = (
            select(BackgroundTask)
            .where(BackgroundTask.status.in_(["running", "pending"]))
            .order_by(BackgroundTask.created_at.desc())
            .limit(100)
        )
        tasks = list(db.scalars(stmt))
        return [_task_to_dict(t) for t in tasks]
    finally:
        db.close()


def get_task_events(task_id: str, limit: int = 200) -> list[dict]:
    """获取任务事件流水。"""
    db = SessionLocal()
    try:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at.asc())
            .limit(limit)
        )
        events = list(db.scalars(stmt))
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "message": e.message,
                "progress": e.progress,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    finally:
        db.close()


def delete_task(task_id: str) -> bool:
    """删除任务记录（仅已结束的任务）。"""
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if not task:
            return False
        if task.status in ("running", "pending"):
            return False  # 进行中的任务不允许删除
        # 删除关联事件
        db.query(TaskEvent).filter(TaskEvent.task_id == task_id).delete()
        db.delete(task)
        db.commit()
        return True
    finally:
        db.close()


def cleanup_old_tasks(days: int = 7) -> int:
    """清理 N 天前已结束的任务。返回删除数量。"""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        old_tasks = list(db.scalars(
            select(BackgroundTask).where(
                BackgroundTask.status.in_(["completed", "failed", "cancelled"]),
                BackgroundTask.finished_at < cutoff,
            )
        ))
        for t in old_tasks:
            db.query(TaskEvent).filter(TaskEvent.task_id == t.id).delete()
            db.delete(t)
        db.commit()
        return len(old_tasks)
    finally:
        db.close()


def recover_stuck_tasks() -> dict:
    """启动时恢复卡住的任务。

    后端崩溃/重启后，pending/running 状态的任务会永远卡住。
    此函数在启动时将这些任务标记为 failed，避免管理台一直显示"加载中"。

    Returns:
        {"pending": 恢复的 pending 任务数, "running": 恢复的 running 任务数}
    """
    db = SessionLocal()
    try:
        # 1. running 状态的任务：后端重启后执行上下文已丢失，标记为 failed
        running_tasks = list(db.scalars(
            select(BackgroundTask).where(BackgroundTask.status == "running")
        ))
        for t in running_tasks:
            t.status = "failed"
            t.finished_at = datetime.utcnow()
            t.error = "后端重启，任务执行中断"
            _add_event(db, t.id, "failed", "后端重启，任务执行中断", progress=t.progress)
            logger.warning("恢复卡住的 running 任务: id=%s title=%s", t.id, t.title)

        # 2. pending 状态超过 5 分钟的任务：创建后未启动，标记为 failed
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        pending_tasks = list(db.scalars(
            select(BackgroundTask).where(
                BackgroundTask.status == "pending",
                BackgroundTask.created_at < cutoff,
            )
        ))
        for t in pending_tasks:
            t.status = "failed"
            t.finished_at = datetime.utcnow()
            t.error = "任务创建后未启动（可能后端崩溃）"
            _add_event(db, t.id, "failed", "任务创建后未启动（可能后端崩溃）", progress=0)
            logger.warning("恢复卡住的 pending 任务: id=%s title=%s", t.id, t.title)

        db.commit()
        result = {"pending": len(pending_tasks), "running": len(running_tasks)}
        if result["pending"] or result["running"]:
            logger.info("任务恢复完成: pending=%d, running=%d", result["pending"], result["running"])
        return result
    except Exception as e:
        logger.error("任务恢复失败: %s", e, exc_info=True)
        db.rollback()
        return {"pending": 0, "running": 0, "error": str(e)}
    finally:
        db.close()


async def retry_task(task_id: str) -> str | None:
    """重试失败任务。需要该任务类型已注册 runner。

    Returns:
        新的 task_id，或 None（无法重试）
    """
    old = get_task(task_id)
    if not old:
        return None
    if old["status"] not in ("failed", "cancelled"):
        return None

    runner = _runners.get(old["task_type"])
    if not runner:
        logger.warning("重试失败：任务类型 %s 未注册 runner", old["task_type"])
        return None

    metadata = old.get("metadata", {})
    new_id = create_task(old["task_type"], old["title"] + "（重试）", metadata)

    # 启动新任务
    async def _run():
        token = _current_task_id.set(new_id)
        try:
            mark_running(new_id)
            await runner(**metadata)
            if is_cancelled(new_id):
                mark_cancelled(new_id)
            else:
                complete_task(new_id)
        except Exception as e:
            logger.exception("任务重试失败: id=%s", new_id)
            fail_task(new_id, str(e))
        finally:
            _current_task_id.reset(token)

    asyncio.create_task(_run())
    return new_id


# ============================================================
# 内部函数
# ============================================================

def _task_to_dict(task: BackgroundTask) -> dict:
    try:
        metadata = json.loads(task.metadata_) if task.metadata_ else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    try:
        result = json.loads(task.result) if task.result else None
    except (json.JSONDecodeError, TypeError):
        result = None
    elapsed = None
    if task.started_at:
        end = task.finished_at or datetime.utcnow()
        elapsed = int((end - task.started_at).total_seconds())
    return {
        "id": task.id,
        "task_type": task.task_type,
        "title": task.title,
        "status": task.status,
        "progress": task.progress,
        "stage": task.stage,
        "total_steps": task.total_steps,
        "current_step": task.current_step,
        "result": result,
        "error": task.error,
        "metadata": metadata,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "elapsed_seconds": elapsed,
        "user_key": task.user_key,
    }


def _add_event(db: Session, task_id: str, event_type: str, message: str, progress: int = -1) -> None:
    event = TaskEvent(
        task_id=task_id,
        event_type=event_type,
        message=message[:1000],
        progress=progress,
    )
    db.add(event)
    db.commit()


def _throttled_push(task_id: str, progress: int | None, stage: str | None) -> None:
    """防抖推送：500ms 内只推最后一次。"""
    now = time.monotonic() * 1000
    last = _push_throttle.get(task_id)
    if last and now - last[0] < PUSH_THROTTLE_MS:
        # 节流期内，暂存最新值，由定时器推送
        _push_throttle[task_id] = (last[0], progress if progress is not None else last[1],
                                    stage if stage is not None else last[2])
        return

    # 立即推送
    _push_throttle[task_id] = (now, progress if progress is not None else 0,
                                stage if stage is not None else "")
    _safe_broadcast({
        "type": "task_progress",
        "task_id": task_id,
        "progress": progress if progress is not None else 0,
        "stage": stage or "",
    })

    # 安排节流期结束后推送最终值
    async def _flush():
        await asyncio.sleep(PUSH_THROTTLE_MS / 1000)
        last = _push_throttle.get(task_id)
        if not last:
            return
        _push_throttle.pop(task_id, None)
        _safe_broadcast({
            "type": "task_progress",
            "task_id": task_id,
            "progress": last[1],
            "stage": last[2],
        })

    try:
        asyncio.get_running_loop()
        asyncio.create_task(_flush())
    except RuntimeError:
        pass  # 非异步上下文不安排 flush


def _safe_broadcast(event: dict) -> None:
    """安全推送 WebSocket，不阻塞、不抛异常。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无运行中的事件循环，跳过
    try:
        from ..routers.ws import manager
        loop.create_task(manager.broadcast(event))
    except Exception:
        pass
