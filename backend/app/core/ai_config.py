"""AI 配置：优先数据库（user_settings，前端可管理），回退文件模板。

安全约定：api_key 只可写入，任何读取接口都不回显明文。
"""
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import UserSetting

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ai_config.json"

DEFAULTS = {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "vision_model": "",
    "intent_model": "",
    "temperature": 0.7,
}

_FALLBACK = None


class AiConfigError(RuntimeError):
    pass


def _file_fallback() -> dict:
    global _FALLBACK
    if _FALLBACK is not None:
        return _FALLBACK
    if CONFIG_PATH.exists():
        _FALLBACK = {**DEFAULTS, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
    else:
        _FALLBACK = dict(DEFAULTS)
    return _FALLBACK


def read_ai_config(db: Session | None = None) -> dict:
    """读取当前 AI 配置（文件兜底 + DB 覆盖）。"""
    cfg = dict(_file_fallback())
    if db is None:
        db = SessionLocal()
        close = True
    else:
        close = False
    try:
        rows = db.execute(
            select(UserSetting.key, UserSetting.value).where(
                UserSetting.key.in_(
                    ["ai.base_url", "ai.api_key", "ai.model", "ai.vision_model", "ai.intent_model", "ai.temperature"]
                )
            )
        )
        for key, value in rows:
            field = key.split(".", 1)[1]
            if field == "temperature":
                cfg["temperature"] = float(value)
            else:
                cfg[field] = value
    finally:
        if close:
            db.close()
    return cfg


def save_ai_config(db: Session, updates: dict) -> dict:
    """写回配置；updates 中 api_key 为空字符串则跳过（不回显也不覆盖）。"""
    field_map = {
        "base_url": "ai.base_url",
        "api_key": "ai.api_key",
        "model": "ai.model",
        "vision_model": "ai.vision_model",
        "intent_model": "ai.intent_model",
        "temperature": "ai.temperature",
    }
    for field, key in field_map.items():
        if field not in updates:
            continue
        value = updates[field]
        if field == "api_key":
            if not value:
                continue  # 空 key 表示不修改
        elif field == "temperature":
            value = str(float(value))
        elif field == "vision_model":
            pass  # 允许空值（清除视觉模型）
        elif not value:
            continue
        row = db.scalar(select(UserSetting).where(UserSetting.key == key))
        if row:
            row.value = str(value)
        else:
            db.add(UserSetting(key=key, value=str(value)))
    db.commit()
    return public_ai_config(db)


def public_ai_config(db: Session) -> dict:
    """对外只读视图：不含 api_key，仅含是否已配置标记。"""
    cfg = read_ai_config(db)
    return {
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "vision_model": cfg.get("vision_model", ""),
        "intent_model": cfg.get("intent_model", ""),
        "temperature": cfg["temperature"],
        "has_key": bool(cfg.get("api_key")),
    }


def require_ai_config(db: Session | None = None) -> dict:
    """读取配置并校验 key 完整性（AI 调用前使用）。"""
    cfg = read_ai_config(db)
    if not cfg.get("base_url"):
        raise AiConfigError("AI 未配置 base_url")
    if not cfg.get("api_key"):
        raise AiConfigError("AI 未配置 API Key：请在管理台「AI 设置」中填写")
    return cfg