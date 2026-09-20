"""审计日志 Pydantic 模型。"""
from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    module: str
    action: str
    target_id: int | None
    target_name: str | None
    detail: str | None
    operator: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogQuery(BaseModel):
    module: str | None = None
    action: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    limit: int = 50
