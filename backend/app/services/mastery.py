"""掌握度引擎：单点更新 + 父节点聚合 + 流水记录 + 状态阈值。

事件影响规则（PRD D11）：
- 选择题对错：规则直接给出目标值变化（对+5~15，错-10）
- 简答/代码：AI 评分 s∈[0,100] → 新掌握度 = 加权 (0.7 当前 + 0.3 s) 后再按难度校准
- 复习权重 ×1.5（由调用方传入 weight 系数）
- 手动自评：直接设置

第一阶段优化：掌握度更新后联动任务完成度
- 掌握度从 <80 涨到 >=80 时，检查关联任务
- 更新关联任务的完成度
- 返回可通过掌握度完成的任务列表（由调用方推送通知）
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, MasteryRecord, Task
from ..models.enums import NodeStatus, TaskStatus

REVIEW_DAYS = 7  # 已掌握但 N 天未复习 → 待复习（由调度器用 review_queue 驱动）


def _status_for(mastery: int) -> str:
    if mastery == 0:
        return NodeStatus.UNTOUCHED
    if mastery < 70:
        return NodeStatus.LEARNING
    if mastery <= 84:
        return NodeStatus.MASTERED
    return NodeStatus.MASTERED  # >=85 仍属已掌握，颜色更深的展示由前端处理


def _recalc_ancestors(db: Session, node: KnowledgeNode) -> None:
    """沿父链聚合：父 = 直接子节点掌握度均值（有子节点时）。"""
    seen: set[int] = set()
    parent_id = node.parent_id
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = db.get(KnowledgeNode, parent_id)
        if not parent:
            break
        children = list(
            db.scalars(select(KnowledgeNode).where(KnowledgeNode.parent_id == parent.id))
        )
        if children:
            parent.mastery = round(sum(c.mastery for c in children) / len(children))
            parent.status = _status_for(parent.mastery)
        parent_id = parent.parent_id


def apply_mastery_update(
    db: Session,
    node_id: int,
    *,
    new_mastery: int,
    reason: str | None,
    source: str,
) -> KnowledgeNode:
    """直接设置掌握度（得分/自评/判定都换算为新值后调用）。

    第一阶段优化：掌握度变化后，自动更新关联任务的完成度。
    如果掌握度从 <80 涨到 >=80，关联任务可通过掌握度完成。
    """
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")
    old = node.mastery
    clamped = max(0, min(100, new_mastery))
    if clamped != old:
        node.mastery = clamped
        node.status = _status_for(clamped)
        db.add(
            MasteryRecord(
                node_id=node.id,
                old_value=old,
                new_value=clamped,
                reason=reason,
                source=source,
            )
        )
        _recalc_ancestors(db, node)
        db.commit()

        # 第一阶段优化：掌握度变化后联动任务完成度
        if clamped != old:
            _update_linked_tasks_completion(db, node_id)

    return node


def _update_linked_tasks_completion(db: Session, node_id: int) -> list[dict]:
    """掌握度变化后，更新绑定该知识点的所有未完成任务的完成度。

    Returns:
        可通过掌握度完成的任务列表（mastery >= 80）
    """
    from .task_completion import update_task_completion, can_complete_by_mastery

    tasks = list(
        db.scalars(
            select(Task).where(
                Task.target_knowledge_id == node_id,
                Task.status != TaskStatus.DONE,
            )
        )
    )

    mastery_ready_tasks = []
    node = db.get(KnowledgeNode, node_id)
    mastery = node.mastery if node else 0

    for task in tasks:
        result = update_task_completion(db, task)
        if can_complete_by_mastery(task, mastery):
            mastery_ready_tasks.append({
                "task_id": task.id,
                "task_title": task.title,
                "mastery": mastery,
                "completion": result["completion"],
                "message": f"知识点「{node.name if node else ''}」掌握度已达{mastery}，可通过掌握度完成任务「{task.title}」",
            })

    return mastery_ready_tasks


def apply_quiz_result(
    db: Session,
    node_id: int,
    *,
    score: int,  # 0-100
    is_objective: bool,
    weight: float = 1.0,
    reason: str = "题目作答",
) -> KnowledgeNode:
    """题目作答更新。目标题：对错换算 ±；主观题：AI 评分混合。"""
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")
    current = node.mastery
    if is_objective:
        if score >= 100:
            delta = (5 + min(10, current // 10 * 2)) * weight  # 连续对递增
            new = current + int(delta)
        else:
            new = current - int(10 * weight)
    else:
        mixed = int(current * 0.7 + score * 0.3)
        # 难度校准：难题控涨速
        calibrate = 1 - 0.15 * (node.difficulty - 3)
        delta = int((mixed - current) * calibrate)
        new = current + delta
    return apply_mastery_update(db, node_id, new_mastery=new, reason=reason, source="quiz_answer")


def self_report(db: Session, node_id: int, mastery: int, reason: str | None = None) -> KnowledgeNode:
    """手动自评覆盖。"""
    return apply_mastery_update(db, node_id, new_mastery=mastery, reason=reason, source="self_report")


def review_visit(db: Session, node_id: int, *, correct: bool) -> KnowledgeNode:
    """复习到期作答（权重 1.5，由 quiz 流程调用）。"""
    return apply_quiz_result(
        db, node_id, score=100 if correct else 0, is_objective=True, weight=1.5, reason="复习作答"
    )
