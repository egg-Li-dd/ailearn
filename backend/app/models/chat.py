"""答疑会话、消息、沉淀建议。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("study_sessions.id"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    mode: Mapped[str] = mapped_column(String(16), default="classroom")
    # 课堂状态（编排引擎唯一事实源）
    active_quiz_id: Mapped[int | None] = mapped_column(Integer)
    active_quiz_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 批量/多题同屏模式的活跃 session（与 active_quiz_id 二选一）
    mainline_json: Mapped[str | None] = mapped_column(Text)  # 主线栈 JSON（C2 启用）
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(16), default="legacy")  # legacy/text/quiz/feedback
    content: Mapped[str] = mapped_column(Text)
    ref_knowledge_ids: Mapped[str | None] = mapped_column(Text)  # JSON 数组文本
    # === AI调用信息（用于显示token消耗、模型、费用）===
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 使用的模型
    ai_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 渠道名称
    ai_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 输入token
    ai_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 输出token
    ai_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 总token
    ai_cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # 费用（元）
    ai_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 耗时（毫秒）
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SedimentSuggestion(Base):
    __tablename__ = "sediment_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")