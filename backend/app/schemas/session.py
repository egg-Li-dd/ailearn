"""会话与任务 Pydantic 模型。"""
from datetime import date, datetime, time

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    type: str = Field(pattern="^(read|practice|memory|think|review)$")
    title: str = Field(min_length=1, max_length=256)
    est_minutes: int | None = Field(default=None, ge=1, le=600)
    target_knowledge_id: int | None = None


class TaskOut(BaseModel):
    id: int
    seq: int
    type: str
    title: str
    target_knowledge_id: int | None
    est_minutes: int | None
    status: str
    # === 任务-检测闭环 ===
    quiz_session_id: int | None = None
    pass_score: int = 80
    actual_score: int | None = None
    passed: bool = False
    attempts: int = 0
    # === 任务完成度（第一阶段优化）===
    completion: int = 0
    best_score: int | None = None
    score_history: str | None = None
    completed_by_mastery: bool = False

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: int
    course_id: int
    course_name: str
    date: date
    status: str
    start_time: time | None
    end_time: time | None
    location: str | None = None
    teacher: str | None = None
    classroom: str | None = None
    tasks: list[TaskOut]

    model_config = {"from_attributes": True}
