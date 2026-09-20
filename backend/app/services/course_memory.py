"""课堂记忆容器服务：课程间上下文继承与开场注入（设计文档 §8.2）。

职责：
- snapshot_from_conversation：会话结束/课程切换时，把当前课堂状态快照到记忆容器
- build_opening：课初加载记忆，聚合薄弱点/到期复习，返回结构化开场上下文
- format_opening_text：把开场上下文转成教练衔接文本（纯模板，不耗 token）
- restore_mainline：30 分钟内的主线栈恢复到 Conversation
"""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CourseMemory, KnowledgeNode, ReviewQueue

logger = logging.getLogger("ailearn.course_memory")

MAINLINE_TTL_MINUTES = 30
WEAK_NODE_LIMIT = 3
WEAK_THRESHOLD = 70
DUE_REVIEW_LIMIT = 5


def get_or_create(db: Session, course_id: int) -> CourseMemory:
    mem = db.scalar(select(CourseMemory).where(CourseMemory.course_id == course_id))
    if mem is None:
        mem = CourseMemory(course_id=course_id)
        db.add(mem)
        db.commit()
        db.refresh(mem)
    return mem


def snapshot_from_conversation(db: Session, conv, course_id: int) -> None:
    """把当前课堂状态快照到课程记忆容器（课程切换/会话结束时调用）。"""
    if course_id is None:
        return
    mem = get_or_create(db, course_id)
    ml: dict = {}
    if conv.mainline_json:
        try:
            ml = json.loads(conv.mainline_json)
        except json.JSONDecodeError:
            ml = {}
    mem.last_knowledge_id = ml.get("active_knowledge")
    mem.pending_quiz_id = conv.active_quiz_id or ml.get("pending_quiz")
    mem.mainline_snapshot = conv.mainline_json
    mem.mainline_expires_at = datetime.utcnow() + timedelta(minutes=MAINLINE_TTL_MINUTES)
    mem.last_conversation_id = conv.id
    db.commit()
    logger.info("course_memory snapshot: course=%d knowledge=%s quiz=%s", course_id, mem.last_knowledge_id, mem.pending_quiz_id)


def build_opening(db: Session, course_id: int) -> dict:
    """聚合课程记忆 + 实时薄弱点 + 到期复习，返回结构化开场上下文。"""
    mem = get_or_create(db, course_id)
    result: dict = {
        "last_knowledge": None,
        "pending_quiz_id": None,
        "weak_nodes": [],
        "due_reviews": [],
        "mainline_valid": False,
        "mainline": None,
    }

    # 上节进度指针
    if mem.last_knowledge_id:
        node = db.get(KnowledgeNode, mem.last_knowledge_id)
        if node:
            result["last_knowledge"] = {"id": node.id, "name": node.name, "mastery": node.mastery}

    # 遗留题目
    result["pending_quiz_id"] = mem.pending_quiz_id

    # 薄弱点：课程内掌握度低于阈值的叶子节点
    weak = list(
        db.scalars(
            select(KnowledgeNode)
            .where(KnowledgeNode.subject_id == course_id, KnowledgeNode.level >= 3)
            .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
            .limit(WEAK_NODE_LIMIT)
        )
    )
    result["weak_nodes"] = [
        {"id": n.id, "name": n.name, "mastery": n.mastery}
        for n in weak
        if n.mastery < WEAK_THRESHOLD
    ]

    # 到期复习（过滤到本课程）
    now = datetime.utcnow()
    due = list(
        db.scalars(
            select(ReviewQueue)
            .where(ReviewQueue.status == "open", ReviewQueue.due_at <= now)
            .order_by(ReviewQueue.due_at)
            .limit(DUE_REVIEW_LIMIT)
        )
    )
    for r in due:
        node = db.get(KnowledgeNode, r.node_id)
        if node and node.subject_id == course_id:
            result["due_reviews"].append({"id": node.id, "name": node.name})

    # 主线栈恢复（30 分钟内有效）
    if mem.mainline_snapshot and mem.mainline_expires_at and mem.mainline_expires_at > now:
        try:
            result["mainline"] = json.loads(mem.mainline_snapshot)
            result["mainline_valid"] = True
        except json.JSONDecodeError:
            pass

    return result


def format_opening_text(opening: dict) -> str | None:
    """把开场上下文格式化成教练衔接文本（纯模板，零 AI 调用）。"""
    parts: list[str] = []
    if opening["last_knowledge"]:
        k = opening["last_knowledge"]
        parts.append(f"上节课我们学到「{k['name']}」（掌握度 {k['mastery']}）。")
    if opening["pending_quiz_id"]:
        parts.append("有一道题还没答完，我们继续。")
    if opening["due_reviews"]:
        names = "、".join(r["name"] for r in opening["due_reviews"])
        parts.append(f"有几个知识点到复习时间了：{names}，建议先过一遍。")
    if opening["weak_nodes"]:
        names = "、".join(n["name"] for n in opening["weak_nodes"])
        parts.append(f"目前薄弱点：{names}，今天重点攻克。")
    if not parts:
        return None
    return " ".join(parts)


def restore_mainline(db: Session, conv, opening: dict) -> bool:
    """如果主线栈在有效期内，恢复到 Conversation。返回是否恢复。"""
    if not opening.get("mainline_valid") or not opening.get("mainline"):
        return False
    ml = opening["mainline"]
    conv.mainline_json = json.dumps(ml, ensure_ascii=False)
    if opening.get("pending_quiz_id"):
        conv.active_quiz_id = opening["pending_quiz_id"]
    elif ml.get("active_knowledge"):
        # 有活跃知识点但没有进行中题目，不自动恢复 quiz
        pass
    db.commit()
    logger.info("course_memory mainline restored: conv=%d", conv.id)
    return True
