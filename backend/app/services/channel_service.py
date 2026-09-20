"""AI 渠道服务：多渠道管理、负载均衡、故障转移。

核心逻辑：
- select_channel(): 按 priority 分组 + weight 随机选择一个可用渠道
- 调用失败时标记渠道状态，下次自动跳过
- 兼容旧的单渠道配置（从 UserSetting 读取并迁移）
"""
import json
import logging
import random
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AiChannel

logger = logging.getLogger("ailearn.channel_service")

# 渠道失败后冷却时间（秒），期间不参与选择
FAILURE_COOLDOWN = 60
# 渠道类型元数据
CHANNEL_TYPES = {
    "openai": {
        "label": "OpenAI 兼容",
        "desc": "DeepSeek / 通义千问 / 智谱 / 月之暗面 等兼容 OpenAI 格式的服务",
        "default_base": "https://api.deepseek.com/v1",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "desc": "Claude 官方 API（非 OpenAI 格式，需单独适配）",
        "default_base": "https://api.anthropic.com",
    },
    "gemini": {
        "label": "Google Gemini",
        "desc": "Gemini 官方 API（非 OpenAI 格式，需单独适配）",
        "default_base": "https://generativelanguage.googleapis.com/v1beta",
    },
}


def parse_models(channel: AiChannel) -> list[str]:
    """解析渠道的模型列表 JSON。"""
    try:
        return json.loads(channel.models or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def serialize_channel(channel: AiChannel, *, include_key: bool = False) -> dict:
    """序列化渠道为字典（默认不含 api_key 明文）。"""
    data = {
        "id": channel.id,
        "name": channel.name,
        "type": channel.type,
        "base_url": channel.base_url,
        "has_key": bool(channel.api_key),
        "models": parse_models(channel),
        "default_model": channel.default_model,
        "vision_model": channel.vision_model,
        "weight": channel.weight,
        "priority": channel.priority,
        "enabled": channel.enabled,
        "status": channel.status,
        "last_test_at": channel.last_test_at.isoformat() if channel.last_test_at else None,
        "last_error": channel.last_error,
        "call_count": channel.call_count,
        "success_count": channel.success_count,
        "total_tokens": channel.total_tokens,
        "temperature": channel.temperature,
        "user_key": channel.user_key,
        "is_global": channel.user_key is None,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
        "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
    }
    if include_key:
        data["api_key"] = channel.api_key
    return data


def list_channels(db: Session, *, only_enabled: bool = False, user_key: str | None = None, scope: str = "all") -> list[AiChannel]:
    """列出渠道，按 priority 升序、weight 降序排列。

    Args:
        user_key: 用户标识，用于过滤私有通道
        scope: 过滤范围
            - "all": 全局通道 + 指定用户的私有通道（默认）
            - "global": 仅全局通道（user_key=NULL）
            - "private": 仅指定用户的私有通道
    """
    stmt = select(AiChannel).order_by(AiChannel.priority.asc(), AiChannel.weight.desc())
    if only_enabled:
        stmt = stmt.where(AiChannel.enabled == True)  # noqa: E712
    if scope == "global":
        stmt = stmt.where(AiChannel.user_key.is_(None))
    elif scope == "private" and user_key:
        stmt = stmt.where(AiChannel.user_key == user_key)
    elif scope == "all" and user_key:
        # 全局通道 + 用户私有通道
        from sqlalchemy import or_
        stmt = stmt.where(or_(AiChannel.user_key.is_(None), AiChannel.user_key == user_key))
    return list(db.scalars(stmt))


def get_channel(db: Session, channel_id: int) -> AiChannel | None:
    return db.get(AiChannel, channel_id)


def create_channel(db: Session, data: dict, *, user_key: str | None = None) -> AiChannel:
    channel = AiChannel(
        name=data.get("name", "未命名渠道"),
        type=data.get("type", "openai"),
        base_url=data.get("base_url", ""),
        api_key=data.get("api_key", ""),
        models=json.dumps(data.get("models", []), ensure_ascii=False),
        default_model=data.get("default_model", ""),
        vision_model=data.get("vision_model", ""),
        weight=int(data.get("weight", 1)),
        priority=int(data.get("priority", 5)),
        enabled=bool(data.get("enabled", True)),
        temperature=float(data.get("temperature", 0.7)),
        user_key=user_key,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def update_channel(db: Session, channel_id: int, data: dict) -> AiChannel | None:
    channel = db.get(AiChannel, channel_id)
    if not channel:
        return None
    fields = ["name", "type", "base_url", "default_model", "vision_model",
              "weight", "priority", "enabled", "temperature"]
    for f in fields:
        if f in data:
            if f in ("weight", "priority"):
                setattr(channel, f, int(data[f]))
            elif f == "enabled":
                setattr(channel, f, bool(data[f]))
            elif f == "temperature":
                setattr(channel, f, float(data[f]))
            else:
                setattr(channel, f, data[f])
    # api_key 特殊处理：空字符串不修改
    if "api_key" in data and data["api_key"]:
        channel.api_key = data["api_key"]
    # models 特殊处理
    if "models" in data:
        channel.models = json.dumps(data["models"], ensure_ascii=False)
    db.commit()
    db.refresh(channel)
    return channel


def delete_channel(db: Session, channel_id: int) -> bool:
    channel = db.get(AiChannel, channel_id)
    if not channel:
        return False
    db.delete(channel)
    db.commit()
    return True


def toggle_channel(db: Session, channel_id: int, enabled: bool) -> AiChannel | None:
    channel = db.get(AiChannel, channel_id)
    if not channel:
        return None
    channel.enabled = enabled
    if enabled:
        channel.status = "unknown"  # 重新启用时重置状态
    db.commit()
    db.refresh(channel)
    return channel


def record_call(db: Session, channel_id: int, *, success: bool, tokens: int = 0, error: str = ""):
    """记录一次调用结果，更新统计和状态。"""
    channel = db.get(AiChannel, channel_id)
    if not channel:
        return
    channel.call_count += 1
    if success:
        channel.success_count += 1
        channel.total_tokens += tokens
        channel.status = "active"
        channel.last_error = ""
    else:
        channel.status = "error"
        channel.last_error = error[:500] if error else ""
    db.commit()


def select_channel(db: Session, *, model: str | None = None, user_key: str | None = None, exclude_ids: set[int] | None = None) -> AiChannel | None:
    """选择一个可用渠道：按 priority 分组，组内按 weight 随机。

    用户隔离逻辑：
    - 如果指定了 user_key，优先从用户私有通道中选择
    - 用户私有通道不可用时，降级到全局通道
    - 未指定 user_key 时，仅从全局通道选择（向后兼容）

    故障转移逻辑：
    1. 筛选 enabled=True 的渠道
    2. 排除 status=error 的渠道（错误渠道不自动恢复，需管理器手动测试通过）
    3. 按 priority 升序取最高优先级组
    4. 组内按 weight 加权随机选择
    5. 如果指定了 model，优先选择包含该模型的渠道
    6. 所有渠道都 error 时，降级为全部启用渠道（保底可用）
    """
    # 优先用户私有通道
    if user_key:
        private_channels = list_channels(db, only_enabled=True, user_key=user_key, scope="private")
        if private_channels:
            result = _select_from_channels(private_channels, model=model, exclude_ids=exclude_ids)
            if result:
                return result
        # 私有通道不可用，降级到全局通道
        global_channels = list_channels(db, only_enabled=True, scope="global")
        return _select_from_channels(global_channels, model=model, exclude_ids=exclude_ids)
    else:
        # 未指定用户，仅全局通道（向后兼容）
        channels = list_channels(db, only_enabled=True, scope="global")
        return _select_from_channels(channels, model=model, exclude_ids=exclude_ids)


def _select_from_channels(channels: list[AiChannel], *, model: str | None = None, exclude_ids: set[int] | None = None) -> AiChannel | None:
    """从给定渠道列表中选择一个可用渠道（内部辅助函数）。"""
    if not channels:
        return None

    # 排除已尝试过的渠道（故障转移）
    if exclude_ids:
        channels = [ch for ch in channels if ch.id not in exclude_ids]

    # 直接排除 status=error 的渠道（错误渠道需管理器手动测试通过后才恢复）
    available = [ch for ch in channels if ch.status != "error"]

    if not available:
        # 所有渠道都 error，降级为全部启用渠道（保底）
        available = channels

    # 如果指定了模型，优先选择包含该模型的渠道
    if model:
        model_match = [ch for ch in available if model in parse_models(ch)]
        if model_match:
            available = model_match

    if not available:
        return None

    # 按 priority 分组，取最高优先级（最小数字）
    groups = defaultdict(list)
    for ch in available:
        groups[ch.priority].append(ch)
    top_priority = min(groups.keys())
    candidates = groups[top_priority]

    if len(candidates) == 1:
        return candidates[0]

    # 按 weight 加权随机
    total_weight = sum(max(1, ch.weight) for ch in candidates)
    pick = random.uniform(0, total_weight)
    cumulative = 0
    for ch in candidates:
        cumulative += max(1, ch.weight)
        if pick <= cumulative:
            return ch
    return candidates[-1]


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _elapsed_seconds(dt) -> float:
    """计算距 now 的秒数，兼容 naive/aware 混存。"""
    from datetime import datetime, timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def get_stats(db: Session) -> dict:
    """获取渠道统计概览。"""
    channels = list_channels(db)
    total = len(channels)
    enabled = sum(1 for ch in channels if ch.enabled)
    active = sum(1 for ch in channels if ch.status == "active")
    error = sum(1 for ch in channels if ch.status == "error")
    total_calls = sum(ch.call_count for ch in channels)
    total_success = sum(ch.success_count for ch in channels)
    total_tokens = sum(ch.total_tokens for ch in channels)
    success_rate = (total_success / total_calls * 100) if total_calls > 0 else 0.0
    return {
        "total": total,
        "enabled": enabled,
        "active": active,
        "error": error,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_tokens": total_tokens,
        "success_rate": round(success_rate, 1),
    }
