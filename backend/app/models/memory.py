"""课堂记忆容器：课程间上下文继承（设计文档 §8.2）。

每门课一个记忆行，记录上节进度、遗留题目、薄弱点引用、主线栈快照。
薄弱点/到期复习不冗余存储，由 build_opening 实时从知识树/复习队列聚合。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class CourseMemory(Base):
    __tablename__ = "course_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), unique=True)

    # 上节进度指针：最后互动的知识点
    last_knowledge_id: Mapped[int | None] = mapped_column(Integer)
    # 遗留未完成：进行中题目
    pending_quiz_id: Mapped[int | None] = mapped_column(Integer)
    # 主线栈快照（JSON），30 分钟内可恢复
    mainline_snapshot: Mapped[str | None] = mapped_column(Text)
    mainline_expires_at: Mapped[datetime | None] = mapped_column(DateTime)

    last_conversation_id: Mapped[int | None] = mapped_column(Integer)
    last_updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
