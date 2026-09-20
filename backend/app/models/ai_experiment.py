"""A/B 测试模型：实验定义 + 事件记录。

用于对比不同 Prompt 版本/模型参数/输出策略的效果。
- AiExperiment：实验定义（名称、变体、流量比例、状态）
- AiExperimentEvent：每次参与实验的调用事件（token、费用、格式正确性等）

建表由启动时 create_all 自动完成，无需手动迁移。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class AiExperiment(Base):
    """A/B 实验定义。

    variants 存储为 JSON 字符串，格式：
    [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]

    status: draft / running / paused / ended
    traffic_pct: 0-100，参与实验的流量比例（其余走默认逻辑）
    """
    __tablename__ = "ai_experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(256), default="")
    # 变体配置（JSON 字符串）
    variants: Mapped[str] = mapped_column(Text, default="[]")
    # 参与实验的流量比例（0-100）
    traffic_pct: Mapped[int] = mapped_column(Integer, default=100)
    # 实验状态
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # 时间
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_experiment_status", "status"),
    )


class AiExperimentEvent(Base):
    """A/B 实验事件：每次参与实验的 AI 调用记录。

    用于按 variant 聚合指标，对比优化效果。
    核心指标：prompt_tokens / completion_tokens / total_tokens / cost / format_valid / duration_ms
    """
    __tablename__ = "ai_experiment_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(Integer, index=True)
    variant: Mapped[str] = mapped_column(String(32), index=True)
    # 分桶用的用户标识（如 node_id / session_id / user_id）
    user_key: Mapped[str] = mapped_column(String(128), default="")
    # 功能类型（quiz / planner / sediment / handwrite 等）
    function_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    # Token 消耗
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 费用预估（元人民币）
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    # 输出格式是否合法（JSON 解析成功）
    format_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    # 重试次数
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    # 耗时（毫秒）
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 时间
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_event_experiment_variant", "experiment_id", "variant"),
        Index("idx_event_experiment_time", "experiment_id", "created_at"),
    )
