"""AI 调用记录服务：记录每次 AI 调用的输入输出、token、费用。

使用 contextvars 传递 function_type，调用方在调用前 set，网关自动读取记录。
"""
import json
import logging
import time
from contextvars import ContextVar

from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..core.pricing import estimate_cost, truncate_text
from ..models import AiCallLog

logger = logging.getLogger("ailearn.call_logger")

# 上下文变量：当前功能类型
_current_function: ContextVar[str] = ContextVar("ai_function_type", default="other")
_current_metadata: ContextVar[dict] = ContextVar("ai_call_metadata", default={})


def set_function_type(function_type: str, **metadata):
    """设置当前调用的功能类型（调用 AI 前使用）。

    Args:
        function_type: 功能类型标识，如 generate/action/quiz/planner/tutor 等
        **metadata: 额外元数据，会存储到记录中

    Returns:
        Token，用于 reset_function_type 恢复
    """
    token1 = _current_function.set(function_type)
    token2 = _current_metadata.set(metadata)
    return (token1, token2)


def reset_function_type(tokens):
    """恢复功能类型上下文。"""
    token1, token2 = tokens
    _current_function.reset(token1)
    _current_metadata.reset(token2)


def get_function_type() -> str:
    """获取当前功能类型。"""
    return _current_function.get()


def get_metadata() -> dict:
    """获取当前元数据。"""
    return _current_metadata.get()


def record_call(
    *,
    model: str,
    messages: list[dict] | str,
    output: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    channel_id: int | None = None,
    channel_name: str = "",
    status: str = "success",
    error_message: str = "",
    duration_ms: int = 0,
    db: Session | None = None,
):
    """记录一次 AI 调用。

    Args:
        model: 模型名
        messages: 输入消息（列表或字符串）
        output: 输出文本
        prompt_tokens: 输入 token
        completion_tokens: 输出 token
        total_tokens: 总 token
        channel_id: 渠道 ID
        channel_name: 渠道名
        status: success/failed
        error_message: 错误信息
        duration_ms: 耗时毫秒
        db: 数据库会话
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # 序列化输入
        if isinstance(messages, str):
            input_text = messages
        else:
            try:
                input_text = json.dumps(messages, ensure_ascii=False)
            except (TypeError, ValueError):
                input_text = str(messages)

        input_chars = len(input_text)
        output_chars = len(output) if output else 0

        # 计算费用
        cost = estimate_cost(model, prompt_tokens, completion_tokens)

        # 从上下文获取功能类型
        function_type = get_function_type()
        metadata = get_metadata()

        # 如果 metadata 中有额外信息，追加到输入
        if metadata:
            try:
                meta_str = json.dumps(metadata, ensure_ascii=False)
                input_text = f"[metadata] {meta_str}\n{input_text}"
            except (TypeError, ValueError):
                pass

        log = AiCallLog(
            function_type=function_type,
            channel_id=channel_id,
            channel_name=channel_name,
            model=model,
            input_text=truncate_text(input_text),
            output_text=truncate_text(output, max_length=8000),
            input_chars=input_chars,
            output_chars=output_chars,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens if total_tokens else (prompt_tokens + completion_tokens),
            cost_estimate=cost,
            status=status,
            error_message=truncate_text(error_message, max_length=2000),
            duration_ms=duration_ms,
        )
        db.add(log)
        db.commit()
        logger.debug(
            "AI 调用记录: func=%s model=%s tokens=%d cost=%.6f status=%s",
            function_type, model, log.total_tokens, cost, status,
        )
    except Exception as e:
        logger.error("记录 AI 调用失败: %s", e, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if close_db:
            db.close()


# 功能类型常量
FUNCTION_TYPES = {
    "generate": "AI 生成数据",
    "action": "AI 调整数据",
    "quiz": "出题",
    "quiz_answer": "判卷",
    "planner": "学习规划",
    "tutor": "答疑辅导",
    "sediment": "知识沉淀",
    "classroom": "课堂互动",
    "handwrite": "手写批改",
    "knowledge": "知识树",
    "stats": "统计周报",
    "review": "复习推荐",
    "intent_classify": "意图识别",
    "test": "连接测试",
    "other": "其他",
}
