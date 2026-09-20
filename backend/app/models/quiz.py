"""题目、作答记录与测验会话。

v2.0 变更：
- 新增 QuizSession（一次课间互动/小测的聚合根）
- 新增 QuizSessionItem（session-题目 多对多）
- QuizAnswer 增加 session_id / attempt，ai_feedback 改为结构化 JSON
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)  # 1-5
    qtype: Mapped[str] = mapped_column(String(16))  # choice/fill/short/code（兼容旧值）
    payload_json: Mapped[str] = mapped_column(Text)  # 统一 v2.0 契约（含 schema_version）
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class QuizSession(Base):
    """一次测验/课间互动会话（多题同屏统一提交的聚合根）。"""

    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    session_type: Mapped[str] = mapped_column(String(16))
    # single / batch / class_break
    status: Mapped[str] = mapped_column(String(20), default="awaiting_submit")
    # awaiting_submit / grading / graded
    current_attempt: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str | None] = mapped_column(String(200))
    generation_errors: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: 出题失败的题目和错误信息
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class QuizSessionItem(Base):
    """session 与题目的多对多关联（含顺序）。"""

    __tablename__ = "quiz_session_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("quiz_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_sessions.id"), index=True, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    user_answer: Mapped[str] = mapped_column(Text)
    # JSON 字符串：多空={"1":"队列","2":"O(n)"}，单选=1，多选=[0,2]，简答="文本"
    score: Mapped[int | None] = mapped_column(Integer)  # 0-100
    ai_feedback: Mapped[str | None] = mapped_column(Text)
    # JSON 字符串：结构化判卷结果（含 blank_results / explanation / error_analysis）
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
