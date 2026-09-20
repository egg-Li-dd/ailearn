"""复习队列服务：到期查询（含 FSRS 四档预览）+ 档位评分。"""
import logging
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, QuizQuestion, ReviewQueue
from ..models.enums import ReviewStatus
from . import review_scheduler
from .mastery import apply_quiz_result
from .quiz import load_payload
from .quiz_contract import QTYPE_RECITE, sanitize_for_client

logger = logging.getLogger("ailearn.review")

# 档位 → 掌握度动量（复习权重 1.5 语义保留：重做惩罚重、轻松奖励重）
_RATING_WEIGHT = (1.5, 0.5, 1.0, 1.5)  # 0重做 1模糊 2记得 3清楚
_RATING_SCORE = (0.0, 0.0, 100.0, 100.0)
_RATING_REASON = ("复习重做", "复习模糊", "复习作答", "复习轻松")


def _node_out(node: KnowledgeNode) -> dict:
    return {
        "node_id": node.id,
        "node_name": node.name,
        "mastery": node.mastery,
        "status": node.status,
    }


def due_items(db: Session, day: date | None = None) -> list[dict]:
    """今日到期复习项（按知识点聚合），附 FSRS 四档作答预览。"""
    day = day or date.today()
    end_of_day = datetime.combine(day, time.max)
    now = datetime.now()
    rows = list(
        db.scalars(
            select(ReviewQueue)
            .where(
                ReviewQueue.status == ReviewStatus.OPEN,
                ReviewQueue.due_at <= end_of_day,
            )
            .order_by(ReviewQueue.due_at)
        )
    )
    out: list[dict] = []
    seen: set[int] = set()
    for r in rows:
        if r.node_id in seen:
            continue  # 防御：同节点多条（理论上 normalize 后不存在）
        seen.add(r.node_id)
        node = db.get(KnowledgeNode, r.node_id)
        if not node:
            continue
        previews = [
            review_scheduler.simulate_rating(r, rate, now) for rate in range(4)
        ]
        item = {
            "id": r.id,
            "node_id": node.id,
            "node_name": node.name,
            "mastery": node.mastery,
            "summary": node.summary,
            "due_at": r.due_at.isoformat(),
            "source": r.source,
            "reps": r.reps or 0,
            "lapses": r.lapses or 0,
            "previews": previews,
        }
        # 附加该知识点的最新背诵题（复习页可直接渲染背诵卡片）
        recite_q = db.scalar(
            select(QuizQuestion)
            .where(
                QuizQuestion.node_id == node.id,
                QuizQuestion.qtype == QTYPE_RECITE,
            )
            .order_by(QuizQuestion.id.desc())
            .limit(1)
        )
        if recite_q:
            rp = load_payload(recite_q)
            item["recite_question"] = {
                "id": recite_q.id,
                "question": rp.get("question", ""),
                "content": rp.get("content", ""),
                "segments": rp.get("segments", []),
                "ladder_steps": rp.get("ladder_steps", 4),
                "explanation": rp.get("explanation", ""),
            }
        # 附加该知识点的最近普通题目（复习页可做题巩固，非背诵题）
        recent_q = db.scalar(
            select(QuizQuestion)
            .where(
                QuizQuestion.node_id == node.id,
                QuizQuestion.qtype != QTYPE_RECITE,
            )
            .order_by(QuizQuestion.id.desc())
            .limit(1)
        )
        if recent_q:
            qp = load_payload(recent_q)
            safe = sanitize_for_client(qp)
            item["recent_question"] = {
                "id": recent_q.id,
                "qtype": recent_q.qtype,
                "difficulty": recent_q.difficulty,
                **safe,
            }
        out.append(item)
    return out


def rate_item(db: Session, queue_id: int, *, rating: int) -> dict:
    """档位评分（0 重做 / 1 模糊 / 2 记得 / 3 清楚）：
    1. FSRS 更新队列状态与下次到期（同一行演进，不新建）
    2. 掌握度按档位动量更新（写入 mastery_records）
    """
    item = db.get(ReviewQueue, queue_id)
    if not item:
        raise ValueError(f"复习项不存在: {queue_id}")
    if item.status != ReviewStatus.OPEN:
        raise ValueError(f"复习项已结束: {queue_id}")
    node = db.get(KnowledgeNode, item.node_id)
    if not node:
        raise ValueError(f"知识点不存在: {item.node_id}")

    now = datetime.now()
    # 1. FSRS 排程
    preview = review_scheduler.apply_rating(item, rating, now)
    # 2. 掌握度
    node = apply_quiz_result(
        db,
        node.id,
        score=_RATING_SCORE[rating],
        is_objective=True,
        weight=_RATING_WEIGHT[rating],
        reason=_RATING_REASON[rating],
    )
    db.commit()
    db.refresh(item)
    return {
        **_node_out(node),
        "queue_id": item.id,
        "rating": rating,
        "rating_name": review_scheduler.RATING_NAMES[rating],
        "reps": item.reps or 0,
        "lapses": item.lapses or 0,
        "next_due_at": preview["due_at"],
        "next_label": preview["label"],
        "previews": [
            review_scheduler.simulate_rating(item, rate, now) for rate in range(4)
        ],
    }
