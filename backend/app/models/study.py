"""学习会话与任务。"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow
from .enums import TaskStatus


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_item_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_items.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    target_knowledge_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_nodes.id"))
    est_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.TODO)
    # === 任务时间跟踪 ===
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_quiz_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    # === 任务-检测闭环 ===
    quiz_session_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_sessions.id"))
    pass_score: Mapped[int] = mapped_column(Integer, default=80)
    actual_score: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # === 任务完成度（第一阶段优化）===
    completion: Mapped[int] = mapped_column(Integer, default=0)  # 0-100 完成度百分比
    best_score: Mapped[int | None] = mapped_column(Integer)  # 历次检测最高分
    score_history: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [{"score":80,"at":"2026-09-01T..."}]
    completed_by_mastery: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否通过掌握度完成
