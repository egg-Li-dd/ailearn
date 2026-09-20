"""审计日志服务。

注意：audit_logs 是全局表，必须使用全局库 session 写入，
不能使用用户库 session（用户库中没有 audit_logs 表）。
"""
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models.audit import AuditLog


def log(db: Session, module: str, action: str, target_id: int | None = None,
        target_name: str | None = None, detail: dict | None = None) -> None:
    """记录审计日志（写入全局库）。

    参数 db 保留为兼容旧调用，但实际写入使用全局库 session。
    审计日志独立于业务事务，即使业务回滚也应保留。
    """
    entry = AuditLog(
        module=module, action=action, target_id=target_id,
        target_name=target_name,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    # 使用全局库 session 写入
    global_db = SessionLocal()
    try:
        global_db.add(entry)
        global_db.commit()
    except Exception:
        global_db.rollback()
        # 审计日志写入失败不影响主业务
        pass
    finally:
        global_db.close()


def query(db: Session, module: str | None = None, action: str | None = None,
          start: datetime | None = None, end: datetime | None = None,
          limit: int = 50) -> list[AuditLog]:
    """查询审计日志。"""
    stmt = select(AuditLog)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at <= end)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def cleanup(db: Session, days: int = 90) -> int:
    """清理 N 天前的日志。"""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    entries = list(db.scalars(select(AuditLog).where(AuditLog.created_at < cutoff)))
    for e in entries:
        db.delete(e)
    db.commit()
    return len(entries)
