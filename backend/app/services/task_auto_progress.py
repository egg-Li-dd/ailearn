"""任务自动推进：定时检查学习中的任务，在截止前自动生成测试题，逾期标记。

物理分库改造：遍历所有 active 用户，逐个用用户库执行检查。

核心逻辑：
1. 任务状态变为 DOING 时，记录 started_at 和 deadline（started_at + est_minutes）
2. 定时检查：deadline - 5分钟 <= now 且未发送测试题 → 自动生成测试题并推送
3. 超过 deadline 且未达标（passed=False）→ 标记 is_overdue=True
4. 重做测试题达标 → 标记 passed=True, status=DONE, is_overdue=False
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from ..core.db import SessionLocal, user_db_manager, get_active_user_keys
from ..models import Conversation, KnowledgeNode, StudySession, Task
from ..models.enums import TaskStatus
from ..routers.ws import manager
from .quiz_session import create_session as create_quiz_session
from .task_quiz import DEFAULT_PASS_SCORE

logger = logging.getLogger("ailearn.task_auto_progress")

# 截止前多少分钟自动发送测试题
AUTO_QUIZ_ADVANCE_MINUTES = 5


def mark_task_started(db, task: Task) -> None:
    """任务开始时记录开始时间和截止时间。"""
    if task.started_at is None:
        task.started_at = datetime.now()
        if task.est_minutes:
            task.deadline = task.started_at + timedelta(minutes=task.est_minutes)
        db.commit()
        logger.info("任务 %d 开始，截止时间: %s", task.id, task.deadline)


async def check_and_auto_progress() -> list[dict]:
    """遍历所有 active 用户，检查学习中的任务，自动推进（生成测试题/标记逾期）。

    返回发生的事件列表，用于广播。
    """
    all_events = []
    user_keys = get_active_user_keys()
    for user_key in user_keys:
        try:
            events = await _check_for_user(user_key)
            all_events.extend(events)
        except Exception:
            logger.exception("task_auto_progress failed for user=%s", user_key)

    # 广播所有事件
    for event in all_events:
        try:
            await manager.broadcast(event)
        except Exception:
            logger.exception("broadcast failed")

    return all_events


async def _check_for_user(user_key: str) -> list[dict]:
    """对单个用户执行任务自动推进检查。"""
    db = user_db_manager.get_session(user_key)
    events = []
    try:
        now = datetime.now()
        # 查询所有待完成和学习中的任务
        active_tasks = list(
            db.scalars(
                select(Task).where(
                    Task.status.in_([TaskStatus.TODO, TaskStatus.DOING]),
                )
            )
        )

        for task in active_tasks:
            # TODO 任务自动变为 DOING 并记录开始时间
            if task.status == TaskStatus.TODO and task.target_knowledge_id:
                task.status = TaskStatus.DOING
                mark_task_started(db, task)
                logger.info("user=%s 任务 %d 自动开始学习", user_key, task.id)

            # 确保开始时间已记录
            if task.started_at is None:
                mark_task_started(db, task)

            if task.deadline is None:
                continue

            # 检查是否需要自动发送测试题（截止前5分钟）
            auto_quiz_time = task.deadline - timedelta(minutes=AUTO_QUIZ_ADVANCE_MINUTES)
            if now >= auto_quiz_time and not task.auto_quiz_sent and task.target_knowledge_id:
                logger.info("user=%s 任务 %d 到达自动出题时间，生成测试题", user_key, task.id)
                try:
                    await _auto_send_quiz(db, task)
                    task.auto_quiz_sent = True
                    db.commit()
                    events.append({
                        "type": "task_auto_quiz",
                        "task_id": task.id,
                        "task_title": task.title,
                        "user_key": user_key,
                        "message": f"任务「{task.title}」学习时间即将结束，自动生成了测试题，请作答。",
                    })
                except Exception as e:
                    logger.error("user=%s 任务 %d 自动出题失败: %s", user_key, task.id, e)

            # 检查是否逾期（超过截止时间且未达标）
            if now > task.deadline and not task.passed and not task.is_overdue:
                task.is_overdue = True
                db.commit()
                logger.info("user=%s 任务 %d 已逾期", user_key, task.id)
                events.append({
                    "type": "task_overdue",
                    "task_id": task.id,
                    "task_title": task.title,
                    "user_key": user_key,
                    "message": f"任务「{task.title}」已逾期，未通过检测。请重做测试题或复习知识点。",
                })

    except Exception:
        logger.exception("task_auto_progress check failed for user=%s", user_key)
    finally:
        db.close()

    return events


async def _auto_send_quiz(db, task: Task) -> None:
    """为任务自动生成测试题并关联。"""
    # 找到任务所属学习会话关联的课堂会话
    study_session = db.get(StudySession, task.session_id)
    if not study_session:
        return

    conv = db.query(Conversation).filter(
        Conversation.course_id == study_session.course_id
    ).order_by(Conversation.id.desc()).first()

    if not conv:
        return

    node = db.get(KnowledgeNode, task.target_knowledge_id)
    if not node:
        return

    # 生成3道测试题
    quiz_session = await create_quiz_session(
        db, conv,
        session_type="task_check",
        title=f"任务检测：{task.title}",
        question_count=3,
        node_ids=[task.target_knowledge_id] * 3,
    )

    task.quiz_session_id = quiz_session.id
    task.pass_score = DEFAULT_PASS_SCORE
    db.commit()
    logger.info("任务 %d 自动生成测试题 session=%d", task.id, quiz_session.id)
