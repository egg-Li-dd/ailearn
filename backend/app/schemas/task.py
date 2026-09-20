"""后台任务 Pydantic 模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TaskOut(BaseModel):
    id: str
    task_type: str
    title: str
    status: str
    progress: int
    stage: str
    total_steps: int
    current_step: int
    result: dict | None
    error: str
    metadata: dict
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    elapsed_seconds: int | None

    model_config = {"from_attributes": True}


class TaskEventOut(BaseModel):
    id: int
    task_type: str = ""
    event_type: str
    message: str
    progress: int
    created_at: str | None

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: list[TaskOut]
    total: int


class TaskCancelResponse(BaseModel):
    ok: bool
    task_id: str
    message: str


class TaskRetryResponse(BaseModel):
    ok: bool
    task_id: str | None
    message: str
