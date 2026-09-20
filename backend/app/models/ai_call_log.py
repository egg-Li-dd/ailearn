"""AI 调用记录模型：追溯每次 AI 生成的输入输出、token 消耗和费用预估。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class AiCallLog(Base):
    __tablename__ = "ai_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 功能类型：generate / action / quiz / planner / tutor / sediment / classroom / handwrite / knowledge / stats / test / other
    function_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    # 渠道信息
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    # 输入输出
    input_text: Mapped[str] = mapped_column(Text, default="")  # 截断存储
    output_text: Mapped[str] = mapped_column(Text, default="")  # 截断存储
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    # Token 消耗
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 费用预估（元人民币）
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    # 状态
    status: Mapped[str] = mapped_column(String(16), default="success")  # success / failed
    error_message: Mapped[str] = mapped_column(Text, default="")
    # 耗时
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 时间
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_call_log_func_time", "function_type", "created_at"),
        Index("idx_call_log_status_time", "status", "created_at"),
    )
