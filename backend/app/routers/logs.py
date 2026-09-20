"""日志聚合路由：统一查询 AI 调用、审计、系统日志。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.db import get_db, get_global_db
from ..schemas.logs import LogListResponse, LogStatsResponse
from ..services import log_aggregator

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


@router.get("", response_model=LogListResponse)
def list_logs(
    source: str = Query(default="all", pattern="^(all|ai_call|audit|system)$"),
    level: str | None = Query(default=None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    module: str | None = None,
    function_type: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_global_db),
):
    """聚合查询日志。"""
    return log_aggregator.query_logs(
        db,
        source=source,
        level=level,
        module=module,
        function_type=function_type,
        keyword=keyword,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=LogStatsResponse)
def log_stats(db: Session = Depends(get_global_db)):
    """日志统计概览。"""
    return log_aggregator.get_stats(db)


@router.delete("")
def cleanup_logs(
    source: str = Query(default="all", pattern="^(all|ai_call|audit|system)$"),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_global_db),
):
    """清理过期日志。"""
    return log_aggregator.cleanup_logs(db, source=source, days=days)
