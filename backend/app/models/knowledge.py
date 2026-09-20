"""知识树、掌握度流水、复习队列。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_nodes.id"))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(128))
    level: Mapped[int] = mapped_column(Integer, default=1)  # 1科目 2章节 3知识点...
    difficulty: Mapped[int] = mapped_column(Integer, default=1)  # 1-5
    mastery: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    status: Mapped[str] = mapped_column(String(16), default="untouched")
    source: Mapped[str] = mapped_column(String(16), default="manual")
    summary: Mapped[str | None] = mapped_column(Text)
    quiz_ids: Mapped[str | None] = mapped_column(Text)  # JSON 数组文本
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # === 新增字段 ===
    sort: Mapped[int] = mapped_column(Integer, default=0)              # 同级排序（拖拽用）
    icon: Mapped[str | None] = mapped_column(String(32))               # 节点图标 emoji
    notes: Mapped[str | None] = mapped_column(Text)                    # 学习笔记/要点/常见误区
    prerequisites: Mapped[str | None] = mapped_column(Text)            # 前置知识点 ID 列表 JSON


class MasteryRecord(Base):
    __tablename__ = "mastery_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True)
    old_value: Mapped[int] = mapped_column(Integer)
    new_value: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(8), default="open")
    source: Mapped[str] = mapped_column(String(16), default="sediment")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # === FSRS 卡片状态（py-fsrs，Anki 同源） ===
    fsrs_d: Mapped[float | None] = mapped_column(Float)  # 难度 1-10
    fsrs_s: Mapped[float | None] = mapped_column(Float)  # 稳定性（天）
    fsrs_state: Mapped[str | None] = mapped_column(String(16), default="learning")  # learning/relearning/review/new
    fsrs_step: Mapped[int | None] = mapped_column(Integer, default=0)  # 当前学习步
    reps: Mapped[int] = mapped_column(Integer, default=0)  # 已复习次数
    lapses: Mapped[int] = mapped_column(Integer, default=0)  # 重做次数