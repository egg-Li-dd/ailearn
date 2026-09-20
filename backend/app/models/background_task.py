"""后台任务模型：统一管理所有异步耗时操作的进度与状态。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class BackgroundTask(Base):
    """后台任务主表（全局库）。

    物理分库后，所有用户的后台任务统一存在全局库，通过 user_key 区分归属。
    """

    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid hex
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    # ai_generate / ai_action / auto_config / knowledge_refine /
    # batch_import / weekly_report / plan_session / custom
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending / running / completed / failed / cancelled
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    stage: Mapped[str] = mapped_column(String(100), default="")  # 当前阶段描述
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(Text, default="")  # JSON 结果摘要
    error: Mapped[str] = mapped_column(Text, default="")
    metadata_: Mapped[str] = mapped_column("metadata", Text, default="")  # 关联ID等 JSON
    user_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # 物理分库：任务归属用户的 db_key，None 表示全局任务（如系统级）
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("idx_bg_task_status_time", "status", "created_at"),
        Index("idx_bg_task_type_time", "task_type", "created_at"),
        Index("idx_bg_task_user_time", "user_key", "created_at"),
    )


class TaskEvent(Base):
    """任务事件流水：用于进度追踪和日志关联（用户库）。"""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    # created / started / progress / stage / log / completed / failed / cancelled
    message: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[int] = mapped_column(Integer, default=-1)  # -1 表示不更新进度
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_task_event_task_time", "task_id", "created_at"),
    )
