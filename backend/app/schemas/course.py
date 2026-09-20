"""课程表相关 Pydantic 模型。"""
from datetime import date, datetime, time

from pydantic import BaseModel, Field


# ---------- 科目 ----------

class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    subject_code: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    sort: int = 0
    icon: str | None = Field(default=None, max_length=32)
    description: str | None = None
    target_days: int | None = Field(default=None, ge=1, le=3650)
    goal_start_date: date | None = None


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    subject_code: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    sort: int | None = None
    icon: str | None = Field(default=None, max_length=32)
    description: str | None = None
    is_archived: bool | None = None
    target_days: int | None = Field(default=None, ge=1, le=3650)
    goal_start_date: date | None = None


class CourseOut(BaseModel):
    id: int
    name: str
    subject_code: str | None
    color: str | None
    sort: int
    icon: str | None = None
    description: str | None = None
    is_archived: bool = False
    target_days: int | None = None
    goal_start_date: date | None = None
    days_remaining: int | None = None  # 计算字段：剩余天数（null=未设置目标）

    model_config = {"from_attributes": True}


class CourseSummaryOut(BaseModel):
    """科目详情汇总。"""
    id: int
    name: str
    subject_code: str | None
    color: str | None
    icon: str | None
    description: str | None
    schedule_count: int = 0
    knowledge_count: int = 0
    avg_mastery: float = 0.0
    recent_sessions: list[dict] = []
    # === 学习目标 ===
    target_days: int | None = None
    goal_start_date: date | None = None
    days_remaining: int | None = None
    daily_knowledge_target: int | None = None  # 每日需攻克知识点数
    mastery_distribution: dict = {}  # {mastered, learning, untouched, review}


class CourseSortItem(BaseModel):
    id: int
    sort: int


class CourseBatchDelete(BaseModel):
    ids: list[int]


class CourseArchiveRequest(BaseModel):
    is_archived: bool


# ---------- 周课表 ----------

class ScheduleItemCreate(BaseModel):
    course_id: int
    weekday: int = Field(ge=0, le=6)  # 0=周一
    start_time: time
    end_time: time
    location: str | None = Field(default=None, max_length=128)
    teacher: str | None = Field(default=None, max_length=64)
    classroom: str | None = Field(default=None, max_length=64)
    week_type: str = Field(default="all", pattern="^(all|odd|even)$")
    color_override: str | None = Field(default=None, max_length=16)


class ScheduleItemUpdate(BaseModel):
    course_id: int | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=128)
    teacher: str | None = Field(default=None, max_length=64)
    classroom: str | None = Field(default=None, max_length=64)
    week_type: str | None = Field(default=None, pattern="^(all|odd|even)$")
    color_override: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None
    sort: int | None = None


class ScheduleItemOut(BaseModel):
    id: int
    course_id: int
    weekday: int
    start_time: time
    end_time: time
    location: str | None
    is_active: bool
    teacher: str | None = None
    classroom: str | None = None
    week_type: str = "all"
    color_override: str | None = None
    sort: int = 0

    model_config = {"from_attributes": True}


class ScheduleItemMoveRequest(BaseModel):
    """拖拽移动请求。"""
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    sort: int = 0


class ScheduleGridOut(BaseModel):
    """网格视图数据。"""
    week_type: str
    time_slots: list[str]
    grid: dict  # {weekday: {time_key: [items]}}
    conflicts: list[dict] = []


# ---------- 课表模板 ----------

class ScheduleTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)


class ScheduleTemplateOut(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- 日期例外 ----------

class ScheduleExceptionCreate(BaseModel):
    date: date
    action: str = Field(pattern="^(add|remove)$")
    course_id: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=256)
    repeat_type: str = Field(default="none", pattern="^(none|daily|weekly|biweekly|monthly)$")
    repeat_config: str | None = None


class ScheduleExceptionUpdate(BaseModel):
    action: str | None = Field(default=None, pattern="^(add|remove)$")
    course_id: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=256)
    repeat_type: str | None = Field(default=None, pattern="^(none|daily|weekly|biweekly|monthly)$")
    repeat_config: str | None = None
    is_active: bool | None = None


class ScheduleExceptionOut(BaseModel):
    id: int
    date: date
    action: str
    course_id: int | None
    start_time: time | None
    end_time: time | None
    reason: str | None = None
    repeat_type: str = "none"
    repeat_config: str | None = None
    is_active: bool = True

    model_config = {"from_attributes": True}


class ExceptionCalendarOut(BaseModel):
    """月历视图数据。"""
    year: int
    month: int
    days: dict  # {day: {date, weekday, exceptions, has_remove, has_add}}
    summary: dict  # {total, remove, add, this_month}


class ExceptionBatchImport(BaseModel):
    items: list[ScheduleExceptionCreate]


class ExceptionBatchDelete(BaseModel):
    ids: list[int]


# ---------- 通用 ----------

class ConflictOut(BaseModel):
    message: str
    existing_item_id: int
    existing_course_name: str
