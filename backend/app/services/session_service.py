"""学习会话生成：周课表 × 日期例外 → 当日 StudySession。"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import utcnow
from ..models import StudySession
from ..models.enums import SessionStatus
from ..models.course import ScheduleException, ScheduleItem

PRE_CLASS_LEAD_MIN = 15  # 课前提前量
REVIEW_TAIL_MIN = 30  # 课后巩固窗口

# 状态机判断（纯函数，便于单测）
# 输入本地时间 now；返回目标状态
def target_status(
    now: datetime,
    start: datetime,
    end: datetime,
    has_unfinished_tasks: bool = False,
) -> str:
    pre_start = start - timedelta(minutes=PRE_CLASS_LEAD_MIN)
    review_end = end + timedelta(minutes=REVIEW_TAIL_MIN)
    if now < pre_start:
        return SessionStatus.SCHEDULED
    if now < start:
        return SessionStatus.PRE_CLASS
    if now < end:
        return SessionStatus.IN_CLASS
    if now < review_end:
        return SessionStatus.REVIEW
    return SessionStatus.OVERDUE if has_unfinished_tasks else SessionStatus.DONE


def _local_datetime(d: date, t: time) -> datetime:
    """本地时间（状态机以本地时间驱动；存储仍 UTC）。"""
    return datetime.combine(d, t)


def _removed_course_ids(db: Session, day: date) -> set[int | None]:
    """当天 remove 例外的课程集合；None 表示全天停课。"""
    rows = db.scalars(
        select(ScheduleException).where(
            ScheduleException.date == day, ScheduleException.action == "remove"
        )
    )
    return {r.course_id for r in rows}


def ensure_today_sessions(db: Session, day: date | None = None) -> list[StudySession]:
    """确保当日会话存在（幂等；同时清理孤儿会话）。返回当日会话列表。"""
    day = day or date.today()

    # 0. 清理孤儿：课表项或加课例外已不存在的当日会话
    for s in list(db.scalars(select(StudySession).where(StudySession.date == day))):
        if s.schedule_item_id is not None:
            if db.get(ScheduleItem, s.schedule_item_id) is None:
                db.delete(s)
        else:
            exc = db.scalar(
                select(ScheduleException).where(
                    ScheduleException.date == day,
                    ScheduleException.action == "add",
                    ScheduleException.course_id == s.course_id,
                )
            )
            if exc is None:
                db.delete(s)
    db.commit()

    removed = _removed_course_ids(db, day)

    # 1. 周课表（跳过被停课的课程）
    items = list(
        db.scalars(
            select(ScheduleItem).where(ScheduleItem.is_active.is_(True))
        )
    )
    for item in items:
        if item.weekday != day.weekday():
            continue
        if None in removed or item.course_id in removed:
            continue
        exists = db.scalar(
            select(StudySession.id).where(
                StudySession.schedule_item_id == item.id,
                StudySession.date == day,
            )
        )
        if not exists:
            db.add(StudySession(schedule_item_id=item.id, course_id=item.course_id, date=day))

    # 2. 加课例外
    adds = list(
        db.scalars(
            select(ScheduleException).where(
                ScheduleException.date == day, ScheduleException.action == "add"
            )
        )
    )
    for exc in adds:
        if exc.course_id is None or exc.start_time is None or exc.end_time is None:
            continue
        exists = db.scalar(
            select(StudySession.id).where(
                StudySession.date == day,
                StudySession.course_id == exc.course_id,
                StudySession.schedule_item_id.is_(None),
            )
        )
        if not exists:
            db.add(
                StudySession(
                    schedule_item_id=None,
                    course_id=exc.course_id,
                    date=day,
                )
            )

    db.commit()
    return list(
        db.scalars(select(StudySession).where(StudySession.date == day).order_by(StudySession.id))
    )


def session_time_range(db: Session, session: StudySession) -> tuple[datetime, datetime] | None:
    """会话起止（本地时间）。返回 None 表示无法确定（异常数据）。"""
    day = session.date
    if session.schedule_item_id is not None:
        item = db.get(ScheduleItem, session.schedule_item_id)
        if not item:
            return None
        return _local_datetime(day, item.start_time), _local_datetime(day, item.end_time)
    # 加课例外
    exc = db.scalar(
        select(ScheduleException).where(
            ScheduleException.date == day,
            ScheduleException.action == "add",
            ScheduleException.course_id == session.course_id,
        )
    )
    if not exc or exc.start_time is None or exc.end_time is None:
        return None
    return _local_datetime(day, exc.start_time), _local_datetime(day, exc.end_time)