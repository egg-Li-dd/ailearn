"""任务完成度计算服务（第一阶段优化）。

完成度公式：
  completion = mastery * 0.4 + best_score * 0.4 + participation * 0.2

其中：
  - mastery: 目标知识点掌握度（0-100）
  - best_score: 历次检测最高分（0-100），未检测过为0
  - participation: 参与度（0-100）
      attempts=0 → 0
      attempts=1 → 50
      attempts>=2 → min(100, 50 + attempts * 15)

任务完成判定：
  completion >= 80 且 best_score >= 60 → DONE

掌握度达标自动完成：
  target_knowledge_id 的 mastery >= 80 时，用户可选择"用掌握度完成任务"
"""
import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, Task
from ..models.enums import TaskStatus

logger = logging.getLogger("ailearn.task_completion")

# 完成度阈值
COMPLETION_PASS_THRESHOLD = 80
MIN_SCORE_FOR_COMPLETION = 60

# 权重
WEIGHT_MASTERY = 0.4
WEIGHT_SCORE = 0.4
WEIGHT_PARTICIPATION = 0.2


def calculate_participation(attempts: int) -> int:
    """计算参与度（0-100）。"""
    if attempts <= 0:
        return 0
    if attempts == 1:
        return 50
    return min(100, 50 + attempts * 15)


def calculate_completion(
    *,
    mastery: int,
    best_score: int | None,
    attempts: int,
) -> int:
    """计算任务完成度（0-100）。

    Args:
        mastery: 目标知识点掌握度
        best_score: 历次检测最高分（None表示未检测过）
        attempts: 检测尝试次数

    Returns:
        完成度百分比（0-100）
    """
    score = best_score if best_score is not None else 0
    participation = calculate_participation(attempts)
    completion = int(
        mastery * WEIGHT_MASTERY
        + score * WEIGHT_SCORE
        + participation * WEIGHT_PARTICIPATION
    )
    return max(0, min(100, completion))


def can_complete_by_completion(task: Task) -> bool:
    """判断是否可以通过完成度完成任务。"""
    return (
        task.completion >= COMPLETION_PASS_THRESHOLD
        and (task.best_score or 0) >= MIN_SCORE_FOR_COMPLETION
    )


def can_complete_by_mastery(task: Task, mastery: int) -> bool:
    """判断是否可以通过掌握度完成任务（mastery >= 80）。"""
    return mastery >= 80 and task.target_knowledge_id is not None


def update_task_completion(db: Session, task: Task) -> dict:
    """更新任务完成度。

    1. 获取目标知识点掌握度
    2. 计算完成度
    3. 如果完成度达标且最低分达标，自动标记DONE

    Returns:
        包含 completion, mastery, best_score, participation, auto_completed 的字典
    """
    mastery = 0
    if task.target_knowledge_id:
        node = db.get(KnowledgeNode, task.target_knowledge_id)
        if node:
            mastery = node.mastery

    best_score = task.best_score if task.best_score is not None else task.actual_score
    attempts = task.attempts or 0
    participation = calculate_participation(attempts)
    completion = calculate_completion(
        mastery=mastery,
        best_score=best_score,
        attempts=attempts,
    )

    task.completion = completion
    auto_completed = False

    # 完成度达标且最低分达标 → 自动完成
    if (
        task.status != TaskStatus.DONE
        and completion >= COMPLETION_PASS_THRESHOLD
        and (best_score or 0) >= MIN_SCORE_FOR_COMPLETION
    ):
        task.status = TaskStatus.DONE
        task.passed = True
        task.is_overdue = False
        auto_completed = True
        logger.info(
            "任务 %d 完成度达标自动完成: completion=%d, mastery=%d, best=%d",
            task.id, completion, mastery, best_score,
        )

    db.commit()
    return {
        "completion": completion,
        "mastery": mastery,
        "best_score": best_score,
        "participation": participation,
        "auto_completed": auto_completed,
    }


def record_score_history(task: Task, score: int) -> None:
    """记录分数历史。

    Args:
        task: 任务对象
        score: 本次检测分数
    """
    history = []
    if task.score_history:
        try:
            history = json.loads(task.score_history)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, TypeError):
            history = []

    history.append({
        "score": score,
        "at": datetime.utcnow().isoformat(),
    })
    # 最多保留20条记录
    if len(history) > 20:
        history = history[-20:]
    task.score_history = json.dumps(history, ensure_ascii=False)

    # 更新最高分
    if task.best_score is None or score > task.best_score:
        task.best_score = score


def complete_by_mastery(db: Session, task: Task) -> dict:
    """用掌握度完成任务。

    前提：target_knowledge_id 的 mastery >= 80

    Returns:
        包含 success, message, mastery, completion 的字典
    """
    if task.status == TaskStatus.DONE:
        return {"success": False, "message": "任务已完成", "completion": task.completion}

    if not task.target_knowledge_id:
        return {"success": False, "message": "任务未绑定知识点", "completion": task.completion}

    node = db.get(KnowledgeNode, task.target_knowledge_id)
    if not node:
        return {"success": False, "message": "知识点不存在", "completion": task.completion}

    mastery = node.mastery
    if mastery < 80:
        return {
            "success": False,
            "message": f"掌握度不足（当前{mastery}，需≥80）",
            "completion": task.completion,
            "mastery": mastery,
        }

    # 用掌握度完成任务
    task.status = TaskStatus.DONE
    task.passed = True
    task.completed_by_mastery = True
    task.actual_score = mastery
    task.is_overdue = False
    if task.best_score is None:
        task.best_score = mastery

    # 重新计算完成度
    result = update_task_completion(db, task)
    logger.info("任务 %d 通过掌握度完成: mastery=%d", task.id, mastery)

    return {
        "success": True,
        "message": "任务已通过掌握度完成",
        "mastery": mastery,
        "completion": result["completion"],
    }


def find_tasks_by_node(db: Session, node_id: int) -> list[Task]:
    """查找绑定了某知识点的所有未完成任务。"""
    return list(
        db.scalars(
            select(Task).where(
                Task.target_knowledge_id == node_id,
                Task.status != TaskStatus.DONE,
            )
        )
    )


def check_mastery_triggered_completion(db: Session, node_id: int) -> list[dict]:
    """知识点掌握度更新后，检查关联任务是否达到"可通过掌握度完成"状态。

    当 mastery 从 <80 涨到 >=80 时调用，返回可通过掌握度完成的任务列表，
    用于推送通知给用户。

    Returns:
        可通过掌握度完成的任务列表（不自动完成，等用户确认）
    """
    node = db.get(KnowledgeNode, node_id)
    if not node or node.mastery < 80:
        return []

    tasks = find_tasks_by_node(db, node_id)
    result = []
    for task in tasks:
        # 更新完成度
        update_task_completion(db, task)
        if task.status != TaskStatus.DONE:
            result.append({
                "task_id": task.id,
                "task_title": task.title,
                "mastery": node.mastery,
                "completion": task.completion,
                "message": f"知识点「{node.name}」掌握度已达{node.mastery}，可通过掌握度完成任务「{task.title}」",
            })
    return result
