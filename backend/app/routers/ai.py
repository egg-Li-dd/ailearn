"""AI 渠道管理路由：CRUD、测试连接、模型列表、统计概览。

保留旧 /config 接口向后兼容；新功能走 /channels 系列。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import Query, APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db, get_global_db
from ..core.ai_config import public_ai_config, save_ai_config
from ..models import UserSetting
from ..services import channel_service, call_logger
from ..services.ai_gateway import AiGatewayError, chat_once
from ..services import task_center

logger = logging.getLogger("ailearn.ai_router")

# 一键配置异步任务存储（内存）
# 一键配置任务统一由 task_center 管理

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ---------- Pydantic Schemas ----------

class ChannelCreate(BaseModel):
    name: str = Field(default="未命名渠道", max_length=64)
    type: str = Field(default="openai", max_length=32)
    base_url: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=512)
    models: list[str] = Field(default_factory=list)
    default_model: str = Field(default="", max_length=128)
    vision_model: str = Field(default="", max_length=128)
    weight: int = Field(default=1, ge=1, le=100)
    priority: int = Field(default=5, ge=1, le=10)
    enabled: bool = Field(default=True)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    user_key: str | None = Field(default=None, max_length=32, description="NULL=全局通道，非NULL=用户私有通道")


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    type: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)  # 空=不修改
    models: list[str] | None = None
    default_model: str | None = Field(default=None, max_length=128)
    vision_model: str | None = Field(default=None, max_length=128)
    weight: int | None = Field(default=None, ge=1, le=100)
    priority: int | None = Field(default=None, ge=1, le=10)
    enabled: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class AiConfigUpdate(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=64)
    vision_model: str | None = Field(default=None, max_length=64)
    intent_model: str | None = Field(default=None, max_length=64)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


# ---------- 渠道 CRUD ----------

@router.get("/channels")
def list_channels(
    db: Session = Depends(get_global_db),
    scope: str = Query(default="all", pattern="^(all|global|private)$"),
    user_key: str | None = Query(default=None),
):
    """列出渠道（不含 api_key 明文）。

    Args:
        scope: all=全局+用户私有, global=仅全局, private=仅指定用户私有
        user_key: 用户标识，scope=private 或 all 时生效
    """
    channels = channel_service.list_channels(db, user_key=user_key, scope=scope)
    return {
        "channels": [channel_service.serialize_channel(ch) for ch in channels],
        "types": channel_service.CHANNEL_TYPES,
    }


@router.get("/channels/stats")
def channel_stats(db: Session = Depends(get_global_db)):
    """渠道统计概览。"""
    return channel_service.get_stats(db)


@router.post("/channels")
def create_channel(payload: ChannelCreate, db: Session = Depends(get_global_db)):
    """创建新渠道。user_key=NULL 创建全局通道，非NULL创建用户私有通道。"""
    data = payload.model_dump()
    user_key = data.pop("user_key", None)
    channel = channel_service.create_channel(db, data, user_key=user_key)
    return channel_service.serialize_channel(channel)


@router.get("/channels/{channel_id}")
def get_channel(channel_id: int, db: Session = Depends(get_global_db)):
    """获取单个渠道详情。"""
    channel = channel_service.get_channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return channel_service.serialize_channel(channel)


@router.put("/channels/{channel_id}")
def update_channel(channel_id: int, payload: ChannelUpdate, db: Session = Depends(get_global_db)):
    """更新渠道（api_key 为空则不修改）。"""
    data = payload.model_dump(exclude_unset=True)
    channel = channel_service.update_channel(db, channel_id, data)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return channel_service.serialize_channel(channel)


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_global_db)):
    """删除渠道。"""
    ok = channel_service.delete_channel(db, channel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return {"ok": True}


@router.post("/channels/{channel_id}/toggle")
def toggle_channel(channel_id: int, db: Session = Depends(get_global_db)):
    """切换渠道启用/禁用状态。"""
    channel = channel_service.get_channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    channel = channel_service.toggle_channel(db, channel_id, not channel.enabled)
    return channel_service.serialize_channel(channel)


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: int, db: Session = Depends(get_global_db)):
    """测试单个渠道的连通性。"""
    channel = channel_service.get_channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    if not channel.api_key:
        raise HTTPException(status_code=400, detail="该渠道未配置 API Key")

    # 更新最后测试时间
    channel.last_test_at = datetime.now(timezone.utc)
    db.commit()

    try:
        reply = await chat_once(
            [{"role": "user", "content": "只回复两个字：正常"}],
            model=channel.default_model or None,
            temperature=0.0,
            db=db,
        )
        channel.status = "active"
        channel.last_error = ""
        db.commit()
        return {"ok": True, "reply": reply.strip()[:100], "channel_id": channel_id}
    except AiGatewayError as e:
        channel.status = "error"
        channel.last_error = str(e)[:500]
        db.commit()
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/channels/{channel_id}/models")
async def fetch_channel_models(channel_id: int, db: Session = Depends(get_global_db)):
    """从渠道 API 拉取可用模型列表（OpenAI 兼容标准 /models 接口）。"""
    import httpx

    channel = channel_service.get_channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    if not channel.api_key:
        raise HTTPException(status_code=400, detail="该渠道未配置 API Key")

    url = channel.base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {channel.api_key}"}
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"模型接口返回 {resp.status_code}")
        data = resp.json()
        models = data.get("data") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise HTTPException(status_code=422, detail="模型接口响应格式异常")
        ids = [m.get("id") or m.get("name") for m in models if isinstance(m, dict)]
        model_list = [i for i in ids if i]
        # 自动保存到渠道
        channel.models = json.dumps(model_list, ensure_ascii=False)
        if not channel.default_model and model_list:
            channel.default_model = model_list[0]
        db.commit()
        return {"models": model_list, "channel_id": channel_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"请求模型列表失败：{e}") from e


# ---------- 旧配置接口（向后兼容） ----------

@router.get("/config")
def get_config(db: Session = Depends(get_global_db)):
    return public_ai_config(db)


@router.put("/config")
def put_config(payload: AiConfigUpdate, db: Session = Depends(get_global_db)):
    try:
        return save_ai_config(
            db,
            payload.model_dump(exclude_unset=True),
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/test")
async def test_connection(db: Session = Depends(get_global_db)):
    """用当前默认渠道/配置发一条最小请求，验证 key 与网络。"""
    try:
        reply = await chat_once(
            [{"role": "user", "content": "只回复两个字：正常"}],
            temperature=0.0,
            db=db,
        )
        return {"ok": True, "reply": reply.strip()[:100]}
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/models")
async def list_models(db: Session = Depends(get_global_db)):
    """从默认渠道拉取模型列表（兼容旧接口）。"""
    channel = channel_service.select_channel(db)
    if channel:
        return await fetch_channel_models(channel.id, db)
    # 回退旧配置
    import httpx
    from ..core.ai_config import AiConfigError, require_ai_config
    try:
        cfg = require_ai_config(db)
    except AiConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    url = cfg["base_url"].rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {cfg['api_key']}"})
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"模型接口返回 {resp.status_code}")
        data = resp.json()
        models = data.get("data") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise HTTPException(status_code=422, detail="模型接口响应格式异常")
        ids = [m.get("id") or m.get("name") for m in models if isinstance(m, dict)]
        return {"models": [i for i in ids if i]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"请求模型列表失败：{e}") from e


# ---------- 兼容旧的 opencode 导入 ----------

@router.get("/opencode-import")
def opencode_import():
    """从本机 OpenCode 配置导入 provider 列表。"""
    import re
    from pathlib import Path

    home = Path.home()
    candidates = [
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".config" / "opencode" / "opencode.json",
        home / ".opencode" / "opencode.jsonc",
    ]
    path = next((p for p in candidates if p.exists()), None)
    auth_candidates = [
        home / ".local" / "share" / "opencode" / "auth.json",
        home / ".config" / "opencode" / "auth.json",
    ]
    auth_path = next((p for p in auth_candidates if p.exists()), None)
    credentials: dict = {}
    if auth_path:
        try:
            credentials = json.loads(auth_path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            credentials = {}

    if not path:
        raise HTTPException(status_code=404, detail="未找到 opencode 配置文件")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"(?<!:)//[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        cfg = json.loads(text)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=422, detail=f"opencode 配置解析失败：{e}") from e

    providers = (cfg.get("provider") or {}).items()
    results = []
    for name, p in providers:
        opts = p.get("options") or {}
        models = list((p.get("models") or {}).keys())
        base_url = opts.get("baseURL")
        if not base_url:
            continue
        api_key = opts.get("apiKey") or credentials.get(name, "") or ""
        results.append(
            {
                "provider": name,
                "base_url": base_url,
                "api_key": api_key,
                "models": models[:5],
            }
        )
    if not results:
        raise HTTPException(status_code=404, detail="opencode 配置中没有可用的 OpenAI 兼容 provider")
    return {"providers": results, "auth_file": str(auth_path) if auth_path else None}


# ============================================================
# AI 调用记录
# ============================================================

@router.get("/calls")
def list_calls(
    db: Session = Depends(get_global_db),
    page: int = 1,
    page_size: int = 20,
    function_type: str | None = None,
    status: str | None = None,
    model: str | None = None,
):
    """AI 调用记录列表（分页 + 筛选）。"""
    from sqlalchemy import desc
    from ..models import AiCallLog

    stmt = select(AiCallLog).order_by(desc(AiCallLog.created_at))

    # 筛选
    if function_type:
        stmt = stmt.where(AiCallLog.function_type == function_type)
    if status:
        stmt = stmt.where(AiCallLog.status == status)
    if model:
        stmt = stmt.where(AiCallLog.model.contains(model))

    # 总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    # 分页
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    rows = db.scalars(stmt).all()

    items = []
    for row in rows:
        items.append({
            "id": row.id,
            "function_type": row.function_type,
            "function_label": call_logger.FUNCTION_TYPES.get(row.function_type, row.function_type),
            "channel_id": row.channel_id,
            "channel_name": row.channel_name,
            "model": row.model,
            "input_chars": row.input_chars,
            "output_chars": row.output_chars,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "total_tokens": row.total_tokens,
            "cost_estimate": row.cost_estimate,
            "status": row.status,
            "error_message": row.error_message[:200] if row.error_message else "",
            "duration_ms": row.duration_ms,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.get("/calls/stats")
def call_stats(db: Session = Depends(get_global_db)):
    """AI 调用统计概览。"""
    from sqlalchemy import func
    from ..models import AiCallLog

    total = db.scalar(select(func.count(AiCallLog.id))) or 0
    success = db.scalar(select(func.count(AiCallLog.id)).where(AiCallLog.status == "success")) or 0
    failed = total - success
    total_tokens = db.scalar(select(func.coalesce(func.sum(AiCallLog.total_tokens), 0))) or 0
    total_cost = db.scalar(select(func.coalesce(func.sum(AiCallLog.cost_estimate), 0.0))) or 0.0
    avg_duration = db.scalar(select(func.coalesce(func.avg(AiCallLog.duration_ms), 0))) or 0

    # 按功能类型统计
    func_stats = db.execute(
        select(AiCallLog.function_type, func.count(AiCallLog.id), func.sum(AiCallLog.total_tokens), func.sum(AiCallLog.cost_estimate))
        .group_by(AiCallLog.function_type)
        .order_by(func.count(AiCallLog.id).desc())
    ).all()

    function_breakdown = []
    for ft, cnt, tokens, cost in func_stats:
        function_breakdown.append({
            "function_type": ft,
            "label": call_logger.FUNCTION_TYPES.get(ft, ft),
            "count": cnt,
            "tokens": tokens or 0,
            "cost": round(cost or 0.0, 6),
        })

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "avg_duration_ms": int(avg_duration),
        "function_breakdown": function_breakdown,
    }


@router.get("/calls/{call_id}")
def get_call(call_id: int, db: Session = Depends(get_global_db)):
    """获取单条调用记录详情（含完整输入输出）。"""
    from ..models import AiCallLog

    row = db.get(AiCallLog, call_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")

    # 解析输入 messages
    input_messages = None
    try:
        if row.input_text.startswith("[metadata]"):
            # 有 metadata 前缀
            parts = row.input_text.split("\n", 1)
            if len(parts) == 2:
                input_messages = json.loads(parts[1])
        else:
            input_messages = json.loads(row.input_text)
    except (json.JSONDecodeError, TypeError):
        input_messages = row.input_text

    return {
        "id": row.id,
        "function_type": row.function_type,
        "function_label": call_logger.FUNCTION_TYPES.get(row.function_type, row.function_type),
        "channel_id": row.channel_id,
        "channel_name": row.channel_name,
        "model": row.model,
        "input_text": row.input_text,
        "input_messages": input_messages,
        "output_text": row.output_text,
        "input_chars": row.input_chars,
        "output_chars": row.output_chars,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "cost_estimate": row.cost_estimate,
        "status": row.status,
        "error_message": row.error_message,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.delete("/calls/{call_id}")
def delete_call(call_id: int, db: Session = Depends(get_global_db)):
    """删除单条调用记录。"""
    from ..models import AiCallLog

    row = db.get(AiCallLog, call_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.delete("/calls")
def clear_calls(db: Session = Depends(get_global_db)):
    """清空所有调用记录。"""
    from ..models import AiCallLog

    count = db.query(AiCallLog).delete()
    db.commit()
    return {"ok": True, "deleted": count}


# ============================================================
# 功能配置（按功能选择模型）
# ============================================================

# 功能配置定义：功能类型 -> 标签、描述
FUNCTION_CONFIGS = {
    "generate": {"label": "AI 生成数据", "desc": "自然语言生成科目/课表/例外/知识节点"},
    "action": {"label": "AI 调整数据", "desc": "选中行 + 调整指令 → 动作 JSON"},
    "quiz": {"label": "出题", "desc": "根据知识点生成测验题目"},
    "quiz_answer": {"label": "判卷", "desc": "自动评判学生答案"},
    "planner": {"label": "学习规划", "desc": "生成学习任务和计划"},
    "tutor": {"label": "答疑辅导", "desc": "对话式答疑和知识点讲解"},
    "sediment": {"label": "知识沉淀", "desc": "从对话中沉淀知识点"},
    "classroom": {"label": "课堂互动", "desc": "课堂场景的 AI 互动"},
    "handwrite": {"label": "手写批改", "desc": "手写作业的识别和批改"},
    "knowledge": {"label": "知识树", "desc": "知识树生成和整理"},
    "stats": {"label": "统计周报", "desc": "生成学习统计和周报"},
    "review": {"label": "复习推荐", "desc": "复习队列和推荐"},
    "intent_classify": {"label": "意图识别", "desc": "课堂输入意图分类（出题/答疑/判卷等）"},
}


@router.get("/function-config")
def get_function_config(
    global_db: Session = Depends(get_global_db),
    user_db: Session = Depends(get_db),
):
    """获取所有功能的模型配置。"""
    from ..models import UserSetting

    # 获取所有已配置的渠道和模型（全局库）
    channels = channel_service.list_channels(global_db, only_enabled=True)
    available_models = []
    for ch in channels:
        models = channel_service.parse_models(ch)
        for m in models:
            available_models.append({
                "channel_id": ch.id,
                "channel_name": ch.name,
                "model": m,
            })

    # 读取每个功能的配置
    configs = {}
    for func_type in FUNCTION_CONFIGS:
        key_prefix = f"ai.func.{func_type}."
        rows = user_db.execute(
            select(UserSetting.key, UserSetting.value).where(UserSetting.key.like(f"{key_prefix}%"))
        ).all()
        cfg = {"channel_id": None, "model": "", "temperature": None}
        for k, v in rows:
            field = k[len(key_prefix):]
            if field == "channel_id":
                cfg["channel_id"] = int(v) if v else None
            elif field == "model":
                cfg["model"] = v
            elif field == "temperature":
                cfg["temperature"] = float(v) if v else None
        configs[func_type] = {**FUNCTION_CONFIGS[func_type], **cfg}

    return {
        "configs": configs,
        "available_models": available_models,
        "channels": [{"id": ch.id, "name": ch.name, "models": channel_service.parse_models(ch)} for ch in channels],
    }


class FunctionConfigUpdate(BaseModel):
    channel_id: int | None = None
    model: str | None = Field(default=None, max_length=128)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


@router.put("/function-config/{function_type}")
def update_function_config(function_type: str, payload: FunctionConfigUpdate, db: Session = Depends(get_db)):
    """更新单个功能的模型配置。"""
    if function_type not in FUNCTION_CONFIGS:
        raise HTTPException(status_code=400, detail=f"未知功能类型: {function_type}")

    key_prefix = f"ai.func.{function_type}."
    updates = payload.model_dump(exclude_unset=True)

    for field, value in updates.items():
        key = f"{key_prefix}{field}"
        row = db.scalar(select(UserSetting).where(UserSetting.key == key))
        str_value = "" if value is None else str(value)
        if row:
            row.value = str_value
        else:
            db.add(UserSetting(key=key, value=str_value))

    db.commit()
    return {"ok": True, "function_type": function_type}


# ============================================================
# 功能配置检测
# ============================================================

@router.post("/function-config/detect")
def detect_function_config(db: Session = Depends(get_global_db)):
    """检测所有功能配置的可行性。

    检测项：
    - 渠道是否存在且启用
    - 模型是否在渠道的模型列表中
    - 渠道是否有 API Key
    """
    results = {}
    for func_type, func_meta in FUNCTION_CONFIGS.items():
        key_prefix = f"ai.func.{func_type}."
        rows = user_db.execute(
            select(UserSetting.key, UserSetting.value).where(UserSetting.key.like(f"{key_prefix}%"))
        ).all()
        cfg = {"channel_id": None, "model": "", "temperature": None}
        for k, v in rows:
            field = k[len(key_prefix):]
            if field == "channel_id":
                cfg["channel_id"] = int(v) if v else None
            elif field == "model":
                cfg["model"] = v
            elif field == "temperature":
                cfg["temperature"] = float(v) if v else None

        # 未配置渠道 = 使用默认自动选择，视为 ok
        if not cfg["channel_id"]:
            results[func_type] = {"status": "ok", "message": "使用默认渠道（自动选择）", "config": cfg}
            continue

        channel = channel_service.get_channel(db, cfg["channel_id"])
        if not channel:
            results[func_type] = {"status": "error", "message": "渠道不存在", "config": cfg}
            continue
        if not channel.enabled:
            results[func_type] = {"status": "error", "message": f"渠道「{channel.name}」已禁用", "config": cfg}
            continue
        if not channel.api_key:
            results[func_type] = {"status": "warning", "message": f"渠道「{channel.name}」未配置 API Key", "config": cfg}
            continue

        # 检查模型
        if cfg["model"]:
            models = channel_service.parse_models(channel)
            if cfg["model"] not in models:
                results[func_type] = {
                    "status": "warning",
                    "message": f"模型「{cfg['model']}」不在渠道「{channel.name}」的模型列表中",
                    "config": cfg,
                }
                continue

        results[func_type] = {"status": "ok", "message": f"渠道「{channel.name}」配置正常", "config": cfg}

    # 统计
    total = len(results)
    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    warning_count = sum(1 for r in results.values() if r["status"] == "warning")
    error_count = sum(1 for r in results.values() if r["status"] == "error")

    return {
        "results": results,
        "summary": {
            "total": total,
            "ok": ok_count,
            "warning": warning_count,
            "error": error_count,
        },
    }


# ============================================================
# 一键配置（AI 决策）
# ============================================================

DEFAULT_AUTO_CONFIG_PROMPT = """你是 AI 模型配置专家。根据可用渠道和模型，为每个功能分配最便宜且可行的模型。

## 分配原则
1. **最便宜且可行**：满足功能需求前提下选最低价模型
2. **功能匹配**：
   - 出题/判卷/学习规划/知识沉淀：需推理能力，选中端模型
   - 答疑辅导/课堂互动：需响应速度，选高性价比模型
   - AI生成数据/AI调整数据：需结构化输出，选稳定模型
   - 手写批改/知识树/统计周报/复习推荐：选高性价比模型
3. **Temperature**：出题/生成0.3-0.5，判卷/调整0.1-0.3，答疑/互动0.7-0.9，其他0.5-0.7

## 可用渠道和模型（价格：输入/输出 元/1K tokens）
{channels_info}

## 功能列表
{functions_info}

## 输出格式
只返回JSON，不要其他文字：
{{"configs":{{"功能key":{{"channel_id":数字,"model":"模型名","temperature":数字}},...}}}}

要求：channel_id和model必须从上面列表中精确选择，每个功能都要配置。"""


def _build_channels_info(channels, top_n: int = 3) -> str:
    """构建渠道和模型信息字符串（含价格），只取每个渠道最便宜的 top_n 个模型。"""
    from ..core.pricing import get_pricing
    lines = []
    for ch in channels:
        if not ch.enabled or not ch.api_key:
            continue
        models = channel_service.parse_models(ch)
        if not models:
            continue
        # 按综合价格（输入+输出）排序，取最便宜的 top_n 个
        model_prices = []
        for m in models:
            input_price, output_price = get_pricing(m)
            total = input_price + output_price
            model_prices.append((m, input_price, output_price, total))
        model_prices.sort(key=lambda x: x[3])
        top_models = model_prices[:top_n]

        lines.append(f"\n### 渠道 ID={ch.id}：{ch.name}（{ch.type}）")
        lines.append(f"Base URL: {ch.base_url}")
        lines.append(f"可用模型（共{len(models)}个，以下为最便宜的{len(top_models)}个）：")
        for m, in_p, out_p, _ in top_models:
            lines.append(f"  - {m}（¥{in_p}/¥{out_p} per 1K tokens）")
    return "\n".join(lines) if lines else "\n（无可用渠道）"


def _build_functions_info() -> str:
    """构建功能列表信息字符串。"""
    lines = []
    for key, meta in FUNCTION_CONFIGS.items():
        lines.append(f"- {key}：{meta['label']} —— {meta['desc']}")
    return "\n".join(lines)


class AutoConfigRequest(BaseModel):
    apply: bool = Field(default=False, description="是否直接应用配置，false 仅返回建议")


async def _execute_auto_config(task_id: str, apply: bool):
    """后台执行一键配置任务。"""
    from ..core.db import SessionLocal
    db = SessionLocal()
    try:
        task_center.update_progress(task_id, progress=10, stage="正在获取可用渠道...")
        # 1. 获取可用渠道
        channels = channel_service.list_channels(db, only_enabled=True)
        available_channels = [ch for ch in channels if ch.api_key and channel_service.parse_models(ch)]

        if not available_channels:
            task_center.fail_task(task_id, error="没有可用的渠道")
            return

        # 2. 获取自动配置设置
        settings = _get_auto_config_settings(db)
        decision_model = settings.get("model")
        custom_prompt = settings.get("prompt", "")

        # 3. 构建 prompt
        channels_info = _build_channels_info(available_channels)
        functions_info = _build_functions_info()
        prompt_template = custom_prompt.strip() if custom_prompt.strip() else DEFAULT_AUTO_CONFIG_PROMPT
        prompt = prompt_template.format(channels_info=channels_info, functions_info=functions_info)

        task_center.update_progress(task_id, progress=30, stage="正在调用 AI 决策...")
        logger.info("一键配置任务 %s：调用 AI 决策，模型=%s", task_id, decision_model)

        # 4. 调用 AI 决策（使用非流式调用，避免后台任务中的流式问题）
        import httpx

        try:
            # 选择渠道：优先选择 status=active 的渠道，排除余额不足的错误渠道
            all_channels = channel_service.list_channels(db, only_enabled=True)
            available = [ch for ch in all_channels if ch.api_key and channel_service.parse_models(ch)]
            # 优先选择 active 状态的渠道
            active_channels = [ch for ch in available if ch.status == "active"]
            if active_channels:
                available = active_channels
            if not available:
                raise Exception("没有可用的渠道（需要至少一个已启用、有 API Key 且状态正常的渠道）")
            # 随机选择一个（或按权重）
            import random
            ch = random.choice(available)

            # 构建请求
            payload = {
                "model": decision_model or ch.default_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "stream": False,
            }

            # 非流式调用
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{ch.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {ch.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                # 安全提取响应内容
                choices = data.get("choices") or []
                if not choices:
                    raise Exception(f"API 返回无 choices: {str(data)[:500]}")
                message = choices[0].get("message") or {}
                raw = message.get("content", "")
                if not raw:
                    # 尝试从其他字段获取内容（某些 API 格式不同）
                    raw = choices[0].get("text", "")
                if not raw:
                    raise Exception(f"API 返回内容为空: {str(data)[:500]}")
                logger.info("一键配置任务 %s AI 响应成功，长度=%d", task_id, len(raw))

            # 记录调用日志
            from ..services import call_logger
            from ..core.pricing import estimate_cost
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            cost = estimate_cost(decision_model or ch.default_model, prompt_tokens, completion_tokens)
            # 设置功能类型（后台任务中 contextvars 不会自动传递）
            ft_tokens = call_logger.set_function_type("auto_config")
            try:
                call_logger.record_call(
                    model=decision_model or ch.default_model,
                    messages=prompt,
                    output=raw,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    channel_id=ch.id,
                    channel_name=ch.name,
                    status="success",
                    duration_ms=0,
                    db=db,
                )
            finally:
                call_logger.reset_function_type(ft_tokens)
            db.commit()

        except Exception as e:
            logger.error("一键配置任务 %s AI 调用失败: %s", task_id, e, exc_info=True)
            task_center.fail_task(task_id, error=f"AI 调用失败：{e}")
            return

        task_center.update_progress(task_id, progress=60, stage="正在解析 AI 返回...")
        # 5. 解析 AI 返回的 JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            task_center.fail_task(task_id, error="AI 返回格式无法解析")
            return
        result = json.loads(json_match.group())
        configs = result.get("configs", {})

        if not isinstance(configs, dict):
            task_center.fail_task(task_id, error="AI 返回的 configs 不是对象")
            return

        task_center.update_progress(task_id, progress=75, stage="正在验证配置...")
        # 6. 验证和清洗配置
        valid_configs = {}
        warnings = []
        available_channel_ids = {ch.id for ch in available_channels}
        channel_models = {ch.id: set(channel_service.parse_models(ch)) for ch in available_channels}

        for func_type, cfg in configs.items():
            if func_type not in FUNCTION_CONFIGS:
                warnings.append(f"未知功能类型：{func_type}，已忽略")
                continue
            if not isinstance(cfg, dict):
                warnings.append(f"功能 {func_type} 的配置不是对象，已忽略")
                continue

            ch_id = cfg.get("channel_id")
            model = cfg.get("model", "")
            temperature = cfg.get("temperature", 0.7)

            if ch_id not in available_channel_ids:
                warnings.append(f"功能 {func_type}：渠道 ID {ch_id} 不可用，已跳过")
                continue
            if model and model not in channel_models.get(ch_id, set()):
                warnings.append(f"功能 {func_type}：模型 {model} 不在渠道 {ch_id} 的列表中，已跳过")
                continue
            try:
                temperature = float(temperature)
                temperature = max(0.0, min(2.0, temperature))
            except (ValueError, TypeError):
                temperature = 0.7

            valid_configs[func_type] = {
                "channel_id": ch_id,
                "model": model,
                "temperature": temperature,
            }

        # 7. 如果 apply=true，应用配置
        applied = []
        if apply:
            for func_type, cfg in valid_configs.items():
                key_prefix = f"ai.func.{func_type}."
                for field, value in [("channel_id", cfg["channel_id"]), ("model", cfg["model"]), ("temperature", cfg["temperature"])]:
                    key = f"{key_prefix}{field}"
                    str_value = "" if value is None else str(value)
                    row = db.scalar(select(UserSetting).where(UserSetting.key == key))
                    if row:
                        row.value = str_value
                    else:
                        db.add(UserSetting(key=key, value=str_value))
                applied.append(func_type)
            db.commit()

        # 8. 完成任务
        task_center.update_progress(task_id, progress=90, stage="配置验证完成")
        task_center.complete_task(task_id, result={
            "ok": True,
            "suggestions": valid_configs,
            "applied": applied,
            "warnings": warnings,
            "total_functions": len(FUNCTION_CONFIGS),
            "configured_count": len(valid_configs),
        })
        logger.info("一键配置任务 %s 完成：%d/%d 功能已配置", task_id, len(valid_configs), len(FUNCTION_CONFIGS))

    except Exception as e:
        logger.error("一键配置任务 %s 失败: %s", task_id, e, exc_info=True)
        task_center.fail_task(task_id, error=str(e))
    finally:
        db.close()


@router.post("/function-config/auto-config")
async def auto_function_config(
    payload: AutoConfigRequest,
):
    """一键配置：创建后台任务，调用 AI 根据最便宜且可行的原则为每个功能分配模型。

    立即返回 task_id，通过 GET /auto-config/{task_id} 查询结果。
    """
    task_id = task_center.create_task(
        task_type="auto_config",
        title="一键 AI 配置",
        metadata={"apply": payload.apply},
    )
    token = task_center._current_task_id.set(task_id)
    try:
        task_center.mark_running(task_id)
        asyncio.create_task(_execute_auto_config(task_id, payload.apply))
    finally:
        task_center._current_task_id.reset(token)
    return {"task_id": task_id, "status": "pending", "message": "任务已创建，AI 正在决策中（通常需要 1-5 分钟）"}


@router.get("/function-config/auto-config/{task_id}")
def get_auto_config_task(task_id: str):
    """查询一键配置任务状态和结果（兼容旧接口）。"""
    task = task_center.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# ============================================================
# 自动配置设置
# ============================================================

def _get_auto_config_settings(db: Session) -> dict:
    """获取自动配置设置（用于决策的 AI 模型和提示词）。"""
    rows = db.execute(
        select(UserSetting.key, UserSetting.value).where(UserSetting.key.like("ai.auto_config.%"))
    ).all()
    settings = {"channel_id": None, "model": "", "prompt": ""}
    for k, v in rows:
        field = k[len("ai.auto_config."):]
        if field == "channel_id":
            settings["channel_id"] = int(v) if v else None
        elif field == "model":
            settings["model"] = v
        elif field == "prompt":
            settings["prompt"] = v
    return settings


class AutoConfigSettingsUpdate(BaseModel):
    channel_id: int | None = None
    model: str | None = Field(default=None, max_length=128)
    prompt: str | None = Field(default=None, max_length=10000)


@router.get("/auto-config-settings")
def get_auto_config_settings(db: Session = Depends(get_db)):
    """获取一键配置的设置（决策用的 AI 模型和提示词）。"""
    settings = _get_auto_config_settings(db)
    # 获取可用渠道列表供前端选择
    channels = channel_service.list_channels(db, only_enabled=True)
    return {
        "settings": settings,
        "channels": [
            {"id": ch.id, "name": ch.name, "models": channel_service.parse_models(ch)}
            for ch in channels if ch.api_key
        ],
        "default_prompt": DEFAULT_AUTO_CONFIG_PROMPT,
    }


@router.put("/auto-config-settings")
def update_auto_config_settings(payload: AutoConfigSettingsUpdate, db: Session = Depends(get_db)):
    """更新一键配置设置。"""
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        key = f"ai.auto_config.{field}"
        str_value = "" if value is None else str(value)
        row = db.scalar(select(UserSetting).where(UserSetting.key == key))
        if row:
            row.value = str_value
        else:
            db.add(UserSetting(key=key, value=str_value))
    db.commit()
    return {"ok": True, "settings": _get_auto_config_settings(db)}
