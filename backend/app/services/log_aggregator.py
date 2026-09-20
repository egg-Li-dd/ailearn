"""日志聚合服务：统一查询 AI 调用日志、审计日志、系统日志。

将三种来源的日志统一格式，支持分页、筛选、关键词搜索、统计。
"""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import AiCallLog, AuditLog, SystemLog
from ..services.call_logger import FUNCTION_TYPES

logger = logging.getLogger("ailearn.log_aggregator")

# 功能类型 label 映射
_FUNC_LABELS = {k: v for k, v in FUNCTION_TYPES.items()}


def query_logs(
    db: Session,
    source: str = "all",  # all / ai_call / audit / system
    level: str | None = None,
    module: str | None = None,
    function_type: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """聚合查询日志，返回统一格式。

    策略：分别查询三个来源，按时间合并排序，内存分页。
    单源查询时直接走该源的分页，效率更高。
    """
    if source == "all":
        return _query_all(db, level, module, function_type, keyword, start, end, page, page_size)
    elif source == "ai_call":
        return _query_ai_calls(db, function_type, keyword, start, end, page, page_size)
    elif source == "audit":
        return _query_audit(db, module, keyword, start, end, page, page_size)
    elif source == "system":
        return _query_system(db, level, module, keyword, start, end, page, page_size)
    else:
        return {"items": [], "total": 0, "total_pages": 0}


def get_stats(db: Session) -> dict:
    """获取日志统计概览。"""
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)

    # 系统日志统计
    sys_today = db.query(func.count(SystemLog.id)).filter(
        SystemLog.created_at >= today_start
    ).scalar() or 0
    sys_errors = db.query(func.count(SystemLog.id)).filter(
        SystemLog.created_at >= today_start,
        SystemLog.level == "ERROR",
    ).scalar() or 0
    sys_warnings = db.query(func.count(SystemLog.id)).filter(
        SystemLog.created_at >= today_start,
        SystemLog.level == "WARNING",
    ).scalar() or 0

    # AI 调用统计
    ai_total = db.query(func.count(AiCallLog.id)).filter(
        AiCallLog.created_at >= today_start
    ).scalar() or 0
    ai_failed = db.query(func.count(AiCallLog.id)).filter(
        AiCallLog.created_at >= today_start,
        AiCallLog.status == "failed",
    ).scalar() or 0
    ai_success_rate = round((1 - ai_failed / ai_total) * 100, 1) if ai_total > 0 else 100.0

    # 按级别分布（系统日志）
    by_level_rows = db.query(
        SystemLog.level, func.count(SystemLog.id)
    ).filter(
        SystemLog.created_at >= today_start
    ).group_by(SystemLog.level).all()
    by_level = {row[0]: row[1] for row in by_level_rows}

    # 按模块分布（系统日志，今日 top 10）
    by_module_rows = db.query(
        SystemLog.module, func.count(SystemLog.id)
    ).filter(
        SystemLog.created_at >= today_start,
        SystemLog.module != "",
    ).group_by(SystemLog.module).order_by(func.count(SystemLog.id).desc()).limit(10).all()
    by_module = {row[0]: row[1] for row in by_module_rows}

    # 最近 24 小时趋势（按小时）
    recent_24h = []
    for i in range(24):
        hour_start = now - timedelta(hours=23 - i)
        hour_start = hour_start.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        errors = db.query(func.count(SystemLog.id)).filter(
            SystemLog.created_at >= hour_start,
            SystemLog.created_at < hour_end,
            SystemLog.level.in_(["ERROR", "CRITICAL"]),
        ).scalar() or 0
        warnings = db.query(func.count(SystemLog.id)).filter(
            SystemLog.created_at >= hour_start,
            SystemLog.created_at < hour_end,
            SystemLog.level == "WARNING",
        ).scalar() or 0
        ai_calls = db.query(func.count(AiCallLog.id)).filter(
            AiCallLog.created_at >= hour_start,
            AiCallLog.created_at < hour_end,
        ).scalar() or 0
        recent_24h.append({
            "hour": hour_start.strftime("%H:00"),
            "errors": errors,
            "warnings": warnings,
            "ai_calls": ai_calls,
        })

    return {
        "today_total": sys_today + ai_total,
        "today_errors": sys_errors + ai_failed,
        "today_warnings": sys_warnings,
        "ai_call_count": ai_total,
        "ai_call_failed": ai_failed,
        "ai_call_success_rate": ai_success_rate,
        "by_level": by_level,
        "by_module": by_module,
        "recent_24h": recent_24h,
    }


def cleanup_logs(db: Session, source: str = "all", days: int = 30) -> dict:
    """清理过期日志。"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = {"ai_call": 0, "audit": 0, "system": 0}

    if source in ("all", "system"):
        rows = db.query(SystemLog).filter(SystemLog.created_at < cutoff).all()
        deleted["system"] = len(rows)
        for r in rows:
            db.delete(r)

    if source in ("all", "audit"):
        rows = db.query(AuditLog).filter(AuditLog.created_at < cutoff).all()
        deleted["audit"] = len(rows)
        for r in rows:
            db.delete(r)

    if source in ("all", "ai_call"):
        # AI 调用日志默认保留更久（90天），除非明确指定
        ai_cutoff = datetime.utcnow() - timedelta(days=max(days, 90))
        rows = db.query(AiCallLog).filter(AiCallLog.created_at < ai_cutoff).all()
        deleted["ai_call"] = len(rows)
        for r in rows:
            db.delete(r)

    db.commit()
    return {"deleted": deleted, "days": days}


# ============================================================
# 内部查询函数
# ============================================================

def _query_all(db, level, module, function_type, keyword, start, end, page, page_size):
    """三源合并查询（内存分页，适合数据量不大的场景）。"""
    all_items = []

    # AI 调用日志
    ai_items = _fetch_ai_calls(db, function_type, keyword, start, end, limit=200)
    all_items.extend(ai_items)

    # 审计日志
    audit_items = _fetch_audit(db, module, keyword, start, end, limit=200)
    all_items.extend(audit_items)

    # 系统日志
    sys_items = _fetch_system(db, level, module, keyword, start, end, limit=200)
    all_items.extend(sys_items)

    # 按时间倒序排序
    all_items.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    total = len(all_items)
    total_pages = (total + page_size - 1) // page_size
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    items = all_items[start_idx:end_idx]

    return {"items": items, "total": total, "total_pages": total_pages}


def _query_ai_calls(db, function_type, keyword, start, end, page, page_size):
    """单源 AI 调用日志分页。"""
    stmt = select(AiCallLog)
    count_stmt = select(func.count(AiCallLog.id))

    if function_type:
        stmt = stmt.where(AiCallLog.function_type == function_type)
        count_stmt = count_stmt.where(AiCallLog.function_type == function_type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            AiCallLog.model.like(like),
            AiCallLog.input_text.like(like),
            AiCallLog.output_text.like(like),
            AiCallLog.error_message.like(like),
        ))
        count_stmt = count_stmt.where(or_(
            AiCallLog.model.like(like),
            AiCallLog.input_text.like(like),
            AiCallLog.output_text.like(like),
            AiCallLog.error_message.like(like),
        ))
    if start:
        stmt = stmt.where(AiCallLog.created_at >= start)
        count_stmt = count_stmt.where(AiCallLog.created_at >= start)
    if end:
        stmt = stmt.where(AiCallLog.created_at <= end)
        count_stmt = count_stmt.where(AiCallLog.created_at <= end)

    total = db.scalar(count_stmt) or 0
    total_pages = (total + page_size - 1) // page_size

    stmt = stmt.order_by(AiCallLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = list(db.scalars(stmt))
    items = [_ai_call_to_entry(r) for r in rows]

    return {"items": items, "total": total, "total_pages": total_pages}


def _query_audit(db, module, keyword, start, end, page, page_size):
    """单源审计日志分页。"""
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))

    if module:
        stmt = stmt.where(AuditLog.module == module)
        count_stmt = count_stmt.where(AuditLog.module == module)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            AuditLog.target_name.like(like),
            AuditLog.detail.like(like),
            AuditLog.action.like(like),
        ))
        count_stmt = count_stmt.where(or_(
            AuditLog.target_name.like(like),
            AuditLog.detail.like(like),
            AuditLog.action.like(like),
        ))
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
        count_stmt = count_stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at <= end)
        count_stmt = count_stmt.where(AuditLog.created_at <= end)

    total = db.scalar(count_stmt) or 0
    total_pages = (total + page_size - 1) // page_size

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = list(db.scalars(stmt))
    items = [_audit_to_entry(r) for r in rows]

    return {"items": items, "total": total, "total_pages": total_pages}


def _query_system(db, level, module, keyword, start, end, page, page_size):
    """单源系统日志分页。"""
    stmt = select(SystemLog)
    count_stmt = select(func.count(SystemLog.id))

    if level:
        stmt = stmt.where(SystemLog.level == level)
        count_stmt = count_stmt.where(SystemLog.level == level)
    if module:
        stmt = stmt.where(SystemLog.module == module)
        count_stmt = count_stmt.where(SystemLog.module == module)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            SystemLog.message.like(like),
            SystemLog.detail.like(like),
            SystemLog.logger_name.like(like),
        ))
        count_stmt = count_stmt.where(or_(
            SystemLog.message.like(like),
            SystemLog.detail.like(like),
            SystemLog.logger_name.like(like),
        ))
    if start:
        stmt = stmt.where(SystemLog.created_at >= start)
        count_stmt = count_stmt.where(SystemLog.created_at >= start)
    if end:
        stmt = stmt.where(SystemLog.created_at <= end)
        count_stmt = count_stmt.where(SystemLog.created_at <= end)

    total = db.scalar(count_stmt) or 0
    total_pages = (total + page_size - 1) // page_size

    stmt = stmt.order_by(SystemLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = list(db.scalars(stmt))
    items = [_system_to_entry(r) for r in rows]

    return {"items": items, "total": total, "total_pages": total_pages}


def _fetch_ai_calls(db, function_type, keyword, start, end, limit=200):
    stmt = select(AiCallLog)
    if function_type:
        stmt = stmt.where(AiCallLog.function_type == function_type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            AiCallLog.model.like(like),
            AiCallLog.input_text.like(like),
            AiCallLog.output_text.like(like),
        ))
    if start:
        stmt = stmt.where(AiCallLog.created_at >= start)
    if end:
        stmt = stmt.where(AiCallLog.created_at <= end)
    stmt = stmt.order_by(AiCallLog.created_at.desc()).limit(limit)
    return [_ai_call_to_entry(r) for r in db.scalars(stmt)]


def _fetch_audit(db, module, keyword, start, end, limit=200):
    stmt = select(AuditLog)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            AuditLog.target_name.like(like),
            AuditLog.detail.like(like),
        ))
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at <= end)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    return [_audit_to_entry(r) for r in db.scalars(stmt)]


def _fetch_system(db, level, module, keyword, start, end, limit=200):
    stmt = select(SystemLog)
    if level:
        stmt = stmt.where(SystemLog.level == level)
    if module:
        stmt = stmt.where(SystemLog.module == module)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            SystemLog.message.like(like),
            SystemLog.detail.like(like),
        ))
    if start:
        stmt = stmt.where(SystemLog.created_at >= start)
    if end:
        stmt = stmt.where(SystemLog.created_at <= end)
    stmt = stmt.order_by(SystemLog.created_at.desc()).limit(limit)
    return [_system_to_entry(r) for r in db.scalars(stmt)]


# ============================================================
# 格式转换
# ============================================================

def _ai_call_to_entry(log: AiCallLog) -> dict:
    label = _FUNC_LABELS.get(log.function_type, log.function_type)
    status_text = "成功" if log.status == "success" else "失败"
    message = f"[{label}] {log.model} - {status_text} ({log.total_tokens} tokens, ¥{log.cost_estimate:.6f})"
    return {
        "id": log.id,
        "source": "ai_call",
        "level": "ERROR" if log.status == "failed" else "INFO",
        "module": "ai_call",
        "function_type": log.function_type,
        "action": "",
        "message": message,
        "detail": {
            "model": log.model,
            "channel": log.channel_name,
            "prompt_tokens": log.prompt_tokens,
            "completion_tokens": log.completion_tokens,
            "total_tokens": log.total_tokens,
            "cost": log.cost_estimate,
            "duration_ms": log.duration_ms,
            "status": log.status,
            "error_message": log.error_message,
            "input_preview": log.input_text[:200] if log.input_text else "",
            "output_preview": log.output_text[:200] if log.output_text else "",
        },
        "task_id": None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _audit_to_entry(log: AuditLog) -> dict:
    action_labels = {
        "create": "创建", "update": "更新", "delete": "删除",
        "batch_delete": "批量删除", "import": "导入",
    }
    action_text = action_labels.get(log.action, log.action)
    message = f"[{log.module}] {action_text} {log.target_name or f'ID={log.target_id}'}"
    return {
        "id": log.id,
        "source": "audit",
        "level": "INFO",
        "module": log.module,
        "function_type": "",
        "action": log.action,
        "message": message,
        "detail": {
            "target_id": log.target_id,
            "target_name": log.target_name,
            "operator": log.operator,
            "detail": log.detail,
        },
        "task_id": None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _system_to_entry(log: SystemLog) -> dict:
    return {
        "id": log.id,
        "source": "system",
        "level": log.level,
        "module": log.module,
        "function_type": "",
        "action": "",
        "message": log.message,
        "detail": {
            "logger_name": log.logger_name,
            "stack_trace": log.detail if log.detail else None,
        },
        "task_id": log.task_id,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
