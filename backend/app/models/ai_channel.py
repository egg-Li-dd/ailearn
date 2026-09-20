"""AI 渠道模型：多渠道管理 + 负载均衡 + 故障转移。

设计参考 One API 的 Channel 概念，但精简为教育场景所需：
- 一个渠道 = 一组（base_url + api_key + 模型列表）配置
- 多渠道启用时按 weight 负载均衡，失败时按 priority 故障转移
- api_key 只写入不回显（读取时返回 has_key 标记）
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class AiChannel(Base):
    __tablename__ = "ai_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="未命名渠道")
    # 渠道类型：openai（兼容 OpenAI 格式，含 DeepSeek/通义/智谱等）、anthropic、gemini
    type: Mapped[str] = mapped_column(String(32), default="openai")
    base_url: Mapped[str] = mapped_column(String(256), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")  # 不回显
    # 可用模型列表，JSON 数组字符串，如 '["deepseek-chat","deepseek-reasoner"]'
    models: Mapped[str] = mapped_column(Text, default="[]")
    default_model: Mapped[str] = mapped_column(String(128), default="")
    vision_model: Mapped[str] = mapped_column(String(128), default="")
    # 负载均衡权重（同优先级内按比例分配）
    weight: Mapped[int] = mapped_column(Integer, default=1)
    # 故障转移优先级：数字越小越优先（1=最高）
    priority: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 运行状态：unknown / active / error
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    # 用量统计
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 默认参数
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    # 用户隔离：NULL 表示全局通道（所有用户可用），非 NULL 表示用户私有通道
    user_key: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
