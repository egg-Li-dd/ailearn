"""科目、周课表、课表例外、课表模板。"""
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow
from .enums import ScheduleAction


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    subject_code: Mapped[str | None] = mapped_column(String(16))
    color: Mapped[str | None] = mapped_column(String(16))  # token 名，如 --subj-ds
    sort: Mapped[int] = mapped_column(Integer, default=0)

    # === 新增字段 ===
    icon: Mapped[str | None] = mapped_column(String(32))        # 科目图标 emoji，如 📐📝🌍
    description: Mapped[str | None] = mapped_column(Text)        # 科目描述
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)  # 归档标记

    # === 学习目标 ===
    target_days: Mapped[int | None] = mapped_column(Integer)     # 目标学习总天数
    goal_start_date: Mapped[date | None] = mapped_column(Date)   # 目标开始日期（手动选择）

    @property
    def days_remaining(self) -> int | None:
        """剩余天数 = target_days - (today - goal_start_date).days；未设置返回 None。"""
        if self.target_days is None or self.goal_start_date is None:
            return None
        from datetime import date as _date
        elapsed = (_date.today() - self.goal_start_date).days
        return max(0, self.target_days - elapsed)


class ScheduleItem(Base):
    """周模板科目条目（weekday + 时间段）。"""

    __tablename__ = "schedule_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    weekday: Mapped[int] = mapped_column(Integer)  # 0=周一 ... 6=周日
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    location: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # === 新增字段 ===
    teacher: Mapped[str | None] = mapped_column(String(64))           # 教师姓名
    classroom: Mapped[str | None] = mapped_column(String(64))         # 教室（与 location 区分）
    week_type: Mapped[str] = mapped_column(String(8), default="all")  # 单双周：all/odd/even
    color_override: Mapped[str | None] = mapped_column(String(16))    # 单独覆盖科目配色
    sort: Mapped[int] = mapped_column(Integer, default=0)              # 同时段排序（拖拽用）


class ScheduleException(Base):
    """日期例外：停课(remove) / 加课(add)。"""

    __tablename__ = "schedule_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(String(8), default=ScheduleAction.REMOVE)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)

    # === 新增字段 ===
    reason: Mapped[str | None] = mapped_column(String(256))            # 例外原因（国庆放假/校运动会等）
    repeat_type: Mapped[str] = mapped_column(String(16), default="none")  # 重复类型：none/daily/weekly/biweekly/monthly
    repeat_config: Mapped[str | None] = mapped_column(Text)            # 重复配置 JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)     # 启用/停用


class ScheduleTemplate(Base):
    """课表模板：保存当前课表快照，可快速应用。"""

    __tablename__ = "schedule_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))                     # 模板名称
    description: Mapped[str | None] = mapped_column(String(256))      # 模板描述
    items_json: Mapped[str] = mapped_column(Text)                      # 课表项快照 JSON
    created_at: Mapped[datetime] = mapped_column(default=utcnow)