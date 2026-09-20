"""FSRS 复习调度器。

核心算法来自开源项目 open-spaced-repetition/py-fsrs（MIT License，
Anki 23.10+ / 墨墨背单词同源算法），本项目仅做参数与数据存储适配。

业务约定：
- 复习粒度按天：学习步 / 再学习步均为 1 天（保留原「每日复习」体感）
- 每个知识点最多一条 open 队列记录（旧 1/3/7 三连由 normalize_legacy_queues 归一）
- 时间出入库均为本地 naive（与 sediment / planner 惯例一致），
  py-fsrs 内部要求 aware-UTC，转换封装在本模块
"""
import logging
from datetime import datetime, timedelta, timezone

import fsrs

from ..models import ReviewQueue

logger = logging.getLogger("ailearn.review_scheduler")

DEFAULT_RETENTION = 0.9
_DAY = timedelta(days=1)

# 全后端共享一个调度器（参数管理台后续可读，本期固定默认）
_scheduler = fsrs.Scheduler(
    desired_retention=DEFAULT_RETENTION,
    learning_steps=(_DAY,),
    relearning_steps=(_DAY,),
    enable_fuzzing=False,
)

RATINGS = (
    fsrs.Rating.Again,  # 0 重做
    fsrs.Rating.Hard,   # 1 模糊
    fsrs.Rating.Good,   # 2 记得
    fsrs.Rating.Easy,   # 3 清楚
)
RATING_NAMES = ("重做", "模糊", "记得", "清楚")

_STATE_MAP = {
    fsrs.State.Learning: "learning",
    fsrs.State.Relearning: "relearning",
    fsrs.State.Review: "review",
}
_STATE_MAP_REV = {v: k for k, v in _STATE_MAP.items()}


def _to_utc(dt: datetime) -> datetime:
    """本地 naive → aware-UTC（py-fsrs 要求）。"""
    if dt.tzinfo is None:
        return dt.astimezone().astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_local(dt: datetime) -> datetime:
    """aware-UTC → 本地 naive（与库内其它时间惯例一致）。"""
    return dt.astimezone().replace(tzinfo=None)


def build_card(queue: ReviewQueue) -> fsrs.Card:
    """把 review_queue 行重建为 fsrs.Card。"""
    state = _STATE_MAP_REV.get(queue.fsrs_state or "learning", fsrs.State.Learning)
    stability = queue.fsrs_s
    difficulty = queue.fsrs_d
    if state in (fsrs.State.Learning, fsrs.State.Relearning) and stability is None:
        stability = 0.21  # py-fsrs 学习卡允许 None，但同批评分需稳定值
    return fsrs.Card(
        card_id=queue.id,
        state=state,
        step=queue.fsrs_step,
        stability=stability,
        difficulty=difficulty,
        due=_to_utc(queue.due_at),
        last_review=_to_utc(queue.due_at - timedelta(days=1)),
    )


def apply_rating(queue: ReviewQueue, rating: int, now: datetime) -> dict:
    """对队列执行档位评分：更新该行 FSRS 状态与 due_at，返回下次预览。"""
    if rating < 0 or rating > 3:
        raise ValueError(f"rating 需为 0-3: {rating}")
    card = build_card(queue)
    new_card, _ = _scheduler.review_card(
        card,
        RATINGS[rating],
        review_datetime=_to_utc(now),
    )
    queue.fsrs_d = new_card.difficulty
    queue.fsrs_s = new_card.stability
    queue.fsrs_state = _STATE_MAP.get(new_card.state, "learning")
    queue.fsrs_step = new_card.step
    queue.reps = (queue.reps or 0) + 1
    if rating == 0:
        queue.lapses = (queue.lapses or 0) + 1
    queue.due_at = _to_local(new_card.due)
    return preview_of(queue, now)


def preview_of(queue: ReviewQueue, now: datetime) -> dict:
    """当前队列到期预览：下次复习时间与人性化文本。"""
    due = queue.due_at
    return {
        "due_at": due.isoformat(),
        "label": describe_delta(due - now),
    }


def simulate_rating(queue: ReviewQueue, rating: int, now: datetime) -> dict:
    """模拟评分（不落库）：App 作答按钮预览「X 天/分钟」用。"""
    if rating < 0 or rating > 3:
        raise ValueError(f"rating 需为 0-3: {rating}")
    card = build_card(queue)
    new_card, _ = _scheduler.review_card(
        card,
        RATINGS[rating],
        review_datetime=_to_utc(now),
    )
    due = _to_local(new_card.due)
    return {"rating": rating, "due_at": due.isoformat(), "label": describe_delta(due - now)}


def describe_delta(delta: timedelta) -> str:
    """人性化时长：分钟 / 小时 / 天。"""
    seconds = delta.total_seconds()
    if seconds <= 60:
        return "现在"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(max(1, minutes))} 分钟"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)} 小时"
    days = seconds / 86400
    return f"{max(1, round(days))} 天"


def normalize_legacy_queues(db, now: datetime | None = None) -> int:
    """归一旧数据：同节点多条 open（原 1/3/7 三连）仅保留最早一条，
    其余置 done；所有既有 open 行补齐 FSRS 初始状态。返回归一的行数。"""
    from sqlalchemy import select

    from ..models.enums import ReviewStatus

    del now
    rows = list(
        db.scalars(
            select(ReviewQueue)
            .where(ReviewQueue.status == ReviewStatus.OPEN)
            .order_by(ReviewQueue.due_at)
        )
    )
    kept: set[int] = set()
    normalized = 0
    for r in rows:
        if r.node_id in kept:
            r.status = ReviewStatus.DONE
            normalized += 1
            continue
        kept.add(r.node_id)
        if r.fsrs_state is None:
            r.fsrs_state = "learning"
            r.fsrs_step = 0
            r.fsrs_d = r.fsrs_d if r.fsrs_d and r.fsrs_d > 0 else 5.0
            r.fsrs_s = None
            r.reps = 0
            r.lapses = 0
            normalized += 1
    if normalized:
        db.commit()
        logger.info("normalize_legacy_queues: %d 行已归一/补齐", normalized)
    return normalized
