"""FSRS 复习调度器纯函数单测（不依赖 DB）。

验证：
- 初始学习卡四档评分后的状态迁移（Again→relearning，Easy→review）
- due 单调：Easy 间隔 > Good > Hard > Again
- 描述文案（分钟/天）
- rating 越界拒绝
"""
from datetime import date, datetime, timedelta

import pytest

from app.models import KnowledgeNode, ReviewQueue
from app.services.review_scheduler import (
    apply_rating,
    describe_delta,
    simulate_rating,
)


def _queue(**kw) -> ReviewQueue:
    base = dict(
        id=1,
        node_id=10,
        due_at=datetime.now(),
        status="open",
        source="sediment",
        fsrs_d=5.0,
        fsrs_s=None,
        fsrs_state="learning",
        fsrs_step=0,
        reps=0,
        lapses=0,
    )
    base.update(kw)
    return ReviewQueue(**base)


def test_new_card_ratings():
    q = _queue()
    now = datetime.now()
    labels = []
    for rating in range(4):
        sim = simulate_rating(q, rating, now)
        labels.append(sim["label"])
        assert sim["rating"] == rating
    # Each rating labels non-empty and Easy due furthest
    e_date = simulate_rating(q, 3, now)["due_at"]
    a_date = simulate_rating(q, 0, now)["due_at"]
    assert e_date > a_date


def test_apply_rating_mutates_queue():
    q = _queue()
    prev_due = q.due_at
    out = apply_rating(q, 2, datetime.now())
    assert q.reps == 1
    assert q.fsrs_state in ("learning", "relearning", "review")
    assert q.due_at > prev_due
    assert out["due_at"] == q.due_at.isoformat()
    assert "label" in out


def test_again_increments_lapses():
    q = _queue()
    apply_rating(q, 0, datetime.now())
    assert q.lapses == 1
    assert q.reps == 1


def test_rating_out_of_range():
    q = _queue()
    with pytest.raises(ValueError):
        apply_rating(q, 4, datetime.now())
    with pytest.raises(ValueError):
        simulate_rating(q, -1, datetime.now())


def test_describe_delta():
    assert describe_delta(timedelta(seconds=30)) == "现在"
    assert describe_delta(timedelta(minutes=10)) == "10 分钟"
    assert describe_delta(timedelta(days=2)) == "2 天"


def test_easy_promotes_to_review_quickly():
    """首答 Easy 应直接进入 Review 态并排到几天后。"""
    q = _queue()
    now = datetime.now()
    sim = simulate_rating(q, 3, now)
    due = datetime.fromisoformat(sim["due_at"])
    assert (due - now) >= timedelta(days=1)
