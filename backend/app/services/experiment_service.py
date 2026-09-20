"""A/B 测试服务：实验配置读取、确定性分桶、事件记录、统计聚合。

设计原则：
- 轻量级：不引入第三方框架，纯 SQLAlchemy + 内存缓存
- 确定性分桶：同一 user_key + experiment_name 始终分到同一 variant
- 非侵入：实验不存在或未运行时，assign_variant 返回 None，调用方走默认逻辑
- 内存缓存：实验配置缓存 60 秒，避免每次调用查库

使用示例（quiz 出题）：
    exp = experiment_service.get_experiment(db, "quiz_prompt_v2")
    variant = experiment_service.assign_variant(exp, f"node_{node.id}") if exp else None
    if variant == "treatment":
        messages = _build_generation_messages_v2(node, qtype)  # 优化版
    else:
        messages = _build_generation_messages(node, qtype)     # 默认版
    raw, usage = await chat_once_with_usage(messages, ...)
    if exp and variant:
        experiment_service.record_event(db, exp, variant, f"node_{node.id}", "quiz", {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "format_valid": data is not None,
            "duration_ms": elapsed_ms,
        })
"""
import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import Float, func, select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import AiExperiment, AiExperimentEvent

logger = logging.getLogger("ailearn.experiment")

# 内存缓存：{name: (expire_at, experiment_obj)}
_exp_cache: dict[str, tuple[float, AiExperiment | None]] = {}
CACHE_TTL = 60  # 秒


def get_experiment(db: Session | None = None, name: str = "") -> AiExperiment | None:
    """获取实验配置（带内存缓存）。

    仅返回 status=running 的实验；draft/paused/ended 均返回 None。
    缓存 60 秒，避免每次 AI 调用都查库。
    注意：ai_experiments 表在全局库，内部自动使用全局库会话。
    """
    now = time.monotonic()
    cached = _exp_cache.get(name)
    if cached and cached[0] > now:
        return cached[1]

    # ai_experiments 在全局库，使用全局库会话
    gdb = SessionLocal()
    try:
        exp = gdb.scalar(
            select(AiExperiment).where(AiExperiment.name == name, AiExperiment.status == "running")
        )
    finally:
        gdb.close()
    _exp_cache[name] = (now + CACHE_TTL, exp)
    return exp


def invalidate_cache(name: str | None = None) -> None:
    """清除实验配置缓存（管理台修改实验后调用）。"""
    if name:
        _exp_cache.pop(name, None)
    else:
        _exp_cache.clear()


def _parse_variants(exp: AiExperiment) -> list[dict]:
    """解析实验的 variants JSON 字段。"""
    try:
        variants = json.loads(exp.variants)
        if isinstance(variants, list):
            return [v for v in variants if isinstance(v, dict) and "name" in v]
    except (json.JSONDecodeError, TypeError):
        logger.warning("实验 %s variants 解析失败，使用空列表", exp.name)
    return []


def assign_variant(exp: AiExperiment | None, user_key: str) -> str | None:
    """确定性分桶：根据 user_key + 实验名分配 variant。

    算法：
    1. bucket = md5(f"{user_key}:{experiment_name}") % 100
    2. 若 bucket >= traffic_pct，返回 None（不参与实验，走默认逻辑）
    3. 否则按 variants 的 weight 比例分配具体 variant

    返回 None 表示不参与实验（调用方应走默认逻辑）。
    """
    if exp is None:
        return None

    variants = _parse_variants(exp)
    if not variants:
        return None

    # 确定性分桶
    hash_input = f"{user_key}:{exp.name}"
    bucket = int(hashlib.md5(hash_input.encode("utf-8")).hexdigest(), 16) % 100

    # 流量过滤
    if bucket >= exp.traffic_pct:
        return None

    # 按 weight 分配 variant
    total_weight = sum(max(1, int(v.get("weight", 1))) for v in variants)
    pick = (bucket % total_weight) + 1  # 1-based
    cumulative = 0
    for v in variants:
        cumulative += max(1, int(v.get("weight", 1)))
        if pick <= cumulative:
            return str(v["name"])

    return str(variants[-1]["name"])


def record_event(
    exp: AiExperiment,
    variant: str,
    user_key: str,
    function_type: str,
    metrics: dict[str, Any],
    db: Session | None = None,
) -> AiExperimentEvent | None:
    """记录一次实验事件。

    注意：ai_experiment_events 表在全局库，内部自动使用全局库会话。

    Args:
        exp: 实验对象
        variant: 分配的 variant 名称
        user_key: 分桶用的用户标识
        function_type: 功能类型（quiz/planner/sediment/handwrite 等）
        metrics: 指标字典，支持以下 key：
            - prompt_tokens: int
            - completion_tokens: int
            - total_tokens: int
            - cost: float
            - format_valid: bool
            - retry_count: int
            - duration_ms: int

    Returns:
        创建的 AiExperimentEvent 对象；失败返回 None（不影响主流程）
    """
    gdb = SessionLocal()
    try:
        event = AiExperimentEvent(
            experiment_id=exp.id,
            variant=variant,
            user_key=str(user_key)[:128],
            function_type=function_type[:32],
            prompt_tokens=int(metrics.get("prompt_tokens", 0)),
            completion_tokens=int(metrics.get("completion_tokens", 0)),
            total_tokens=int(metrics.get("total_tokens", 0)),
            cost=float(metrics.get("cost", 0.0)),
            format_valid=bool(metrics.get("format_valid", True)),
            retry_count=int(metrics.get("retry_count", 0)),
            duration_ms=int(metrics.get("duration_ms", 0)),
        )
        gdb.add(event)
        gdb.commit()
        return event
    except Exception as e:
        logger.error("记录实验事件失败（不影响主流程）: exp=%s variant=%s error=%s",
                     exp.name, variant, e)
        try:
            gdb.rollback()
        except Exception:
            pass
        return None
    finally:
        gdb.close()


def get_experiment_stats(db: Session, experiment_id: int) -> list[dict]:
    """按 variant 聚合实验统计指标。

    Returns:
        list[dict]，每个元素含：
        - variant: str
        - calls: int 调用次数
        - avg_prompt_tokens: float
        - avg_completion_tokens: float
        - avg_total_tokens: float
        - avg_cost: float
        - format_valid_rate: float (0-1)
        - avg_duration_ms: float
    """
    rows = db.execute(
        select(
            AiExperimentEvent.variant,
            func.count(AiExperimentEvent.id).label("calls"),
            func.avg(AiExperimentEvent.prompt_tokens).label("avg_prompt_tokens"),
            func.avg(AiExperimentEvent.completion_tokens).label("avg_completion_tokens"),
            func.avg(AiExperimentEvent.total_tokens).label("avg_total_tokens"),
            func.avg(AiExperimentEvent.cost).label("avg_cost"),
            func.avg(AiExperimentEvent.format_valid.cast(Float)).label("format_valid_rate"),
            func.avg(AiExperimentEvent.duration_ms).label("avg_duration_ms"),
        )
        .where(AiExperimentEvent.experiment_id == experiment_id)
        .group_by(AiExperimentEvent.variant)
    ).all()

    return [
        {
            "variant": r.variant,
            "calls": r.calls,
            "avg_prompt_tokens": round(float(r.avg_prompt_tokens or 0), 2),
            "avg_completion_tokens": round(float(r.avg_completion_tokens or 0), 2),
            "avg_total_tokens": round(float(r.avg_total_tokens or 0), 2),
            "avg_cost": round(float(r.avg_cost or 0), 6),
            "format_valid_rate": round(float(r.format_valid_rate or 0), 4),
            "avg_duration_ms": round(float(r.avg_duration_ms or 0), 2),
        }
        for r in rows
    ]


def list_experiments(db: Session, status: str | None = None) -> list[AiExperiment]:
    """列出所有实验（管理台用）。"""
    stmt = select(AiExperiment).order_by(AiExperiment.id.desc())
    if status:
        stmt = stmt.where(AiExperiment.status == status)
    return list(db.scalars(stmt))


def create_experiment(
    db: Session,
    name: str,
    description: str,
    variants: list[dict],
    traffic_pct: int = 100,
) -> AiExperiment:
    """创建新实验（管理台用）。"""
    exp = AiExperiment(
        name=name,
        description=description,
        variants=json.dumps(variants, ensure_ascii=False),
        traffic_pct=max(0, min(100, traffic_pct)),
        status="draft",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    invalidate_cache(name)
    return exp


def update_experiment_status(db: Session, experiment_id: int, status: str) -> AiExperiment | None:
    """更新实验状态（管理台用）。"""
    exp = db.get(AiExperiment, experiment_id)
    if not exp:
        return None
    exp.status = status
    db.commit()
    db.refresh(exp)
    invalidate_cache(exp.name)
    return exp
