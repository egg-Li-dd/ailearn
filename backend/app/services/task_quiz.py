"""任务-检测闭环：为任务生成/获取检测题，判断通过/未通过。

核心流程：
1. 任务布置时绑定知识点（target_knowledge_id）
2. 用户点击任务 → ensure_task_quiz 生成检测题（3-5题）
3. 用户答题 → submit_task_quiz 提交判卷
4. 完成度 = 掌握度×40% + 最高分×40% + 参与度×20%
5. 完成度≥80 且 最高分≥60 → 任务标记 DONE
6. 未通过 → 记录分数历史，更新完成度，可重做
"""
import logging

from sqlalchemy.orm import Session

from ..models import Conversation, KnowledgeNode, Task
from ..models.enums import TaskStatus
from .quiz_session import create_session as create_quiz_session
from .quiz_session import session_to_client_response
from .task_completion import (
    record_score_history,
    update_task_completion,
)

logger = logging.getLogger("ailearn.task_quiz")

DEFAULT_QUIZ_COUNT = 3  # 默认检测题数量
DEFAULT_PASS_SCORE = 80  # 默认通过阈值（百分制）


async def ensure_task_quiz(db: Session, task: Task) -> dict | None:
    """确保任务有关联的检测题；没有则生成。返回检测题会话的客户端响应。

    生成规则：
    - 任务必须有 target_knowledge_id
    - 题目数量：默认3题，知识点核心要素多则最多5题
    - 题型：填空→单选→判断→多选 循环
    """
    if task.quiz_session_id is not None:
        # 已有检测题，直接返回
        from ..models import QuizSession
        session = db.get(QuizSession, task.quiz_session_id)
        if session:
            return session_to_client_response(db, session)

    if task.target_knowledge_id is None:
        logger.info("task %d 无 target_knowledge_id，跳过检测题生成", task.id)
        return None

    node = db.get(KnowledgeNode, task.target_knowledge_id)
    if not node:
        logger.warning("task %d 的知识点 %d 不存在", task.id, task.target_knowledge_id)
        return None

    # 根据知识点核心要素数量决定题目数（3-5题）
    quiz_count = DEFAULT_QUIZ_COUNT
    try:
        import json
        if node.notes:
            data = json.loads(node.notes)
            params = data.get("params", {})
            core_elements = params.get("core_elements", [])
            if isinstance(core_elements, list) and len(core_elements) > 3:
                quiz_count = min(5, len(core_elements))
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    # 找一个会话用于创建 quiz_session（create_quiz_session 需要 conv）
    conv = _get_conversation_for_task(db, task)
    if conv is None:
        logger.warning("task %d 无法找到关联会话，跳过检测题生成", task.id)
        return None

    # 题型循环：填空→单选→判断→多选
    from .quiz_contract import QTYPE_FILL_CLOZE, QTYPE_SINGLE_CHOICE, QTYPE_JUDGE, QTYPE_MULTIPLE_CHOICE
    type_cycle = [QTYPE_FILL_CLOZE, QTYPE_SINGLE_CHOICE, QTYPE_JUDGE, QTYPE_MULTIPLE_CHOICE]
    question_types = [type_cycle[i % len(type_cycle)] for i in range(quiz_count)]

    try:
        quiz_session = await create_quiz_session(
            db, conv,
            session_type="task_check",
            title=f"任务检测：{task.title}",
            question_count=quiz_count,
            node_ids=[task.target_knowledge_id] * quiz_count,  # 同一知识点出多题
            question_types=question_types,
        )
        task.quiz_session_id = quiz_session.id
        task.pass_score = DEFAULT_PASS_SCORE
        db.commit()
        logger.info("task %d 生成检测题 session=%d, count=%d", task.id, quiz_session.id, quiz_count)
        return session_to_client_response(db, quiz_session)
    except Exception as e:
        logger.error("task %d 检测题生成失败: %s", task.id, e)
        return None


def _get_conversation_for_task(db: Session, task: Task) -> Conversation | None:
    """为任务找到一个可用的会话（用于创建 quiz_session）。

    优先用任务所属学习会话关联的课堂会话；没有则用课程下最新的会话。
    """
    from ..models import StudySession
    study_session = db.get(StudySession, task.session_id)
    if study_session:
        # 找该课程下最新的会话
        conv = db.query(Conversation).filter(
            Conversation.course_id == study_session.course_id
        ).order_by(Conversation.id.desc()).first()
        if conv:
            return conv
    # 兜底：取最新会话
    return db.query(Conversation).order_by(Conversation.id.desc()).first()


def submit_task_quiz_result(db: Session, task: Task, score: int, passed: bool) -> dict:
    """提交检测题结果，更新任务状态和完成度。

    新逻辑：
    1. 记录分数历史和最高分
    2. 更新 attempts
    3. 计算完成度（掌握度×40% + 最高分×40% + 参与度×20%）
    4. 完成度≥80 且 最高分≥60 → 自动标记DONE
    5. 传统判定（score≥pass_score）也直接标记DONE（兼容旧逻辑）

    Returns:
        包含 completion, best_score, auto_completed 的字典
    """
    task.actual_score = score
    task.passed = passed
    task.attempts = (task.attempts or 0) + 1

    # 记录分数历史和最高分
    record_score_history(task, score)

    # 传统判定：直接通过
    if passed:
        task.status = TaskStatus.DONE
        task.is_overdue = False
        logger.info("task %d 通过检测（score=%d），标记完成", task.id, score)
        db.commit()
        # 更新完成度
        completion_result = update_task_completion(db, task)
        return {
            "completion": completion_result["completion"],
            "best_score": task.best_score,
            "auto_completed": True,
            "completed_by": "score",
        }

    # 未通过：更新完成度，可能自动完成
    logger.info("task %d 未通过检测（score=%d, threshold=%d），更新完成度",
                task.id, score, task.pass_score)
    db.commit()

    completion_result = update_task_completion(db, task)
    return {
        "completion": completion_result["completion"],
        "best_score": task.best_score,
        "auto_completed": completion_result["auto_completed"],
        "completed_by": "completion" if completion_result["auto_completed"] else None,
    }
