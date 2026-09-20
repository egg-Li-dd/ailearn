"""日志聚合 Pydantic 模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class LogEntryOut(BaseModel):
    """统一日志条目（多源聚合）。"""
    id: int | str
    source: str  # ai_call / audit / system
    level: str = ""
    module: str = ""
    function_type: str = ""
    action: str = ""
    message: str = ""
    detail: dict | None = None
    task_id: str | None = None
    created_at: datetime | str | None

    model_config = {"from_attributes": True}


class LogListResponse(BaseModel):
    items: list[LogEntryOut]
    total: int
    total_pages: int


class LogStatsResponse(BaseModel):
    today_total: int
    today_errors: int
    today_warnings: int
    ai_call_count: int
    ai_call_failed: int
    ai_call_success_rate: float
    by_level: dict[str, int]
    by_module: dict[str, int]
    recent_24h: list[dict]
