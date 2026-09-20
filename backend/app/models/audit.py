"""审计日志：记录关键写操作。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class AuditLog(Base):
    """操作审计日志。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(32), index=True)        # 模块：course/schedule/exception/knowledge/ai
    action: Mapped[str] = mapped_column(String(16), index=True)        # 操作：create/update/delete/batch_delete/import
    target_id: Mapped[int | None] = mapped_column(Integer)              # 操作对象 ID
    target_name: Mapped[str | None] = mapped_column(String(256))        # 操作对象名称（冗余，便于展示）
    detail: Mapped[str | None] = mapped_column(Text)                    # 变更详情 JSON
    operator: Mapped[str] = mapped_column(String(32), default="admin")  # 操作人
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
