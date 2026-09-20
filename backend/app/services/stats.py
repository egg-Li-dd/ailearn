"""统计服务：看板数据聚合（单用户规模，内存聚合即可）。"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Course, KnowledgeNode, Message, QuizAnswer, Task
from ..models.enums import TaskStatus

LOCAL_TZ = timezone(timedelta(hours=8))  # 展示层本地时区（东八区）


def _local_day(dt: datetime) -> date:
    return dt.astimezone(LOCAL_TZ).date()


def overview(db: Session) -> dict:
    """总览：连续学习天数 / 本周学时 / 累计任务数。"""
    # 学习活动日期：消息 + 答题 + 完成任务（tasks 无完成时间，用会话日期近似）
    activity: set[date] = set()
    for m in db.scalars(select(Message.created_at)):
        activity.add(_local_day(m))
    for a in db.scalars(select(QuizAnswer.created_at)):
        activity.add(_local_day(a))

    # 连续天数：从今天往回数
    streak = 0
    probe = date.today()
    while probe in activity:
        streak += 1
        probe -= timedelta(days=1)

    # 本周学时：完成的阅读/练习等任务分钟数（会话日期在本周）
    from ..models import StudySession

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    rows = db.execute(
        select(Task.est_minutes, StudySession.date)
        .join(StudySession, Task.session_id == StudySession.id)
        .where(Task.status == TaskStatus.DONE)
    )
    week_minutes = sum(
        (m or 0) for m, d in rows if d and week_start <= d <= today
    )

    total_done = db.scalar(
        select(Task.id).where(Task.status == TaskStatus.DONE).limit(1)
    )
    return {
        "streak_days": streak,
        "week_minutes": week_minutes,
        "total_tasks_done": _count_tasks(db),
    }


def _count_tasks(db: Session) -> int:
    # count 用 func
    from sqlalchemy import func

    return db.scalar(select(func.count(Task.id)).where(Task.status == TaskStatus.DONE)) or 0


def radar(db: Session) -> list[dict]:
    """各科目掌握度（科目根节点掌握度；无树时取全树均值）。"""
    out: list[dict] = []
    for course in db.scalars(select(Course).order_by(Course.sort, Course.id)):
        root = db.scalar(
            select(KnowledgeNode).where(
                KnowledgeNode.subject_id == course.id,
                KnowledgeNode.parent_id.is_(None),
            )
        )
        if root is not None:
            value = root.mastery
        else:
            nodes = list(
                db.scalars(
                    select(KnowledgeNode).where(KnowledgeNode.subject_id == course.id)
                )
            )
            value = round(sum(n.mastery for n in nodes) / len(nodes)) if nodes else 0
        out.append({"course_id": course.id, "name": course.name, "mastery": value})
    return out


def heatmap(db: Session, days: int = 84) -> list[dict]:
    """近 N 天活跃度（0-4 档）：任务完成=1，答题=2，消息=0.5 · 封顶 4。"""
    score_map: dict[date, float] = defaultdict(float)

    for m in db.scalars(select(Message.created_at)):
        score_map[_local_day(m)] += 0.5
    for a in db.scalars(select(QuizAnswer.created_at)):
        score_map[_local_day(a)] += 2.0

    from ..models import StudySession

    rows = db.execute(
        select(Task.id, StudySession.date).join(StudySession, Task.session_id == StudySession.id)
        .where(Task.status == TaskStatus.DONE)
    )
    for _, d in rows:
        if d:
            score_map[d] += 1.0

    today = date.today()
    out: list[dict] = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        raw = score_map.get(day, 0.0)
        if raw <= 0:
            level = 0
        elif raw <= 2:
            level = 1
        elif raw <= 4:
            level = 2
        elif raw <= 8:
            level = 3
        else:
            level = 4
        out.append({"date": day.isoformat(), "level": level})
    return out