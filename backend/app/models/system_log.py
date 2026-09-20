"""系统日志模型：结构化存储 WARNING 及以上级别的运行日志。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class SystemLog(Base):
    """系统运行日志（WARNING+ 自动写入，INFO 级可选写入）。"""

    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(16), index=True)  # DEBUG/INFO/WARNING/ERROR/CRITICAL
    logger_name: Mapped[str] = mapped_column(String(128), index=True)  # ailearn.scheduler 等
    message: Mapped[str] = mapped_column(Text)
    module: Mapped[str] = mapped_column(String(64), default="", index=True)  # 业务模块归类
    detail: Mapped[str] = mapped_column(Text, default="")  # 异常堆栈等
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # 关联后台任务
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_sys_log_level_time", "level", "created_at"),
        Index("idx_sys_log_module_time", "module", "created_at"),
    )
