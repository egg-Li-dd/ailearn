"""审计日志路由。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.db import get_db, get_global_db
from ..schemas.audit import AuditLogOut
from ..services import audit_service

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    module: str | None = None,
    action: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_global_db),
):
    """查询审计日志。"""
    return audit_service.query(db, module=module, action=action, start=start, end=end, limit=limit)


@router.delete("/cleanup")
def cleanup_audit_logs(days: int = Query(default=90, ge=1), db: Session = Depends(get_global_db)):
    """清理 N 天前的审计日志。"""
    deleted = audit_service.cleanup(db, days=days)
    return {"deleted": deleted, "days": days}
