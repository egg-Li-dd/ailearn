"""AI 网关：多渠道 OpenAI 兼容 chat/completions（支持流式 + 重试 + 故障转移）。

调用流程：
1. channel_service.select_channel() 按优先级+权重选择渠道
2. 发起请求，失败时自动尝试下一个渠道（故障转移）
3. 记录每次调用的成功/失败到渠道统计
4. 记录每次调用的输入输出、token、费用到调用日志
5. 兼容旧单渠道配置（无渠道时回退到 ai_config）
"""
import asyncio
import json
import logging
import time

import httpx
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, user_db_manager
from ..core.user_context import get_current_user_key
from . import call_logger
from ..core.ai_config import AiConfigError, require_ai_config
from ..services import channel_service
from ..services import call_logger

logger = logging.getLogger("ailearn.ai_gateway")

DEFAULT_TIMEOUT = 120.0
MAX_RETRIES = 2  # 单渠道内重试次数
MAX_CHANNEL_FAILOVER = 3  # 最多切换渠道次数
RETRY_DELAY_BASE = 1.0  # 秒，指数退避基数


class AiGatewayError(RuntimeError):
    pass


def _is_retryable(status_code: int) -> bool:
    """判断是否可重试：429 限流、5xx 服务端错误、网络异常。"""
    return status_code in (429, 500, 502, 503, 504)



# 功能类型自动推断规则：(关键词列表, function_type)，按优先级排序
_FUNCTION_TYPE_RULES: list[tuple[list[str], str]] = [
    (["出题引擎", "生成练习题", "生成题目", "根据知识点生成"], "quiz"),
    (["阅卷老师", "评分反馈", "判卷", "批改答案", "详细评分", "单选题进行"], "quiz_answer"),
    (["规划教练", "学习规划", "生成课前", "生成课中", "生成任务", "规划Agent", "为考研学习会话"], "planner"),
    (["答疑", "辅导", "教练", "讲解", "你是一个老师", "你是AI教练", "学习助手"], "tutor"),
    (["知识沉淀", "沉淀知识点", "从对话中", "总结知识点", "知识提取"], "sediment"),
    (["课堂互动", "课堂场景", "课堂助手"], "classroom"),
    (["手写批改", "手写识别", "手写作业", "识别手写"], "handwrite"),
    (["知识树", "知识节点", "知识点细化", "细化知识", "知识图谱"], "knowledge"),
    (["统计周报", "学习统计", "学习报告", "周报", "数据分析"], "stats"),
    (["复习推荐", "复习队列", "艾宾浩斯", "复习计划"], "review"),
    (["意图识别", "意图分类", "判断用户意图"], "intent_classify"),
    (["生成数据", "自然语言生成", "生成科目", "生成课表"], "generate"),
    (["调整数据", "动作JSON", "调整指令", "选中行"], "action"),
    (["只回复两个字", "连接测试", "测试连接"], "test"),
]



def _infer_function_type(messages: list[dict] | str) -> str:
    """根据输入消息的 system/user prompt 关键词自动推断功能类型。

    当调用方未显式 set_function_type 时作为兜底，避免日志全记为 other。
    """
    if isinstance(messages, str):
        text = messages
    else:
        parts = []
        for m in messages:
            if isinstance(m, dict):
                c = m.get("content", "")
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, list):
                    for item in c:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
        text = "\n".join(parts)

    text_lower = text.lower()
    for keywords, func_type in _FUNCTION_TYPE_RULES:
        for kw in keywords:
            if kw.lower() in text_lower:
                return func_type
    return "other"


def _build_client(base_url: str, api_key: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=DEFAULT_TIMEOUT,
    )


def _get_channel_config(db: Session, *, model: str | None = None, user_key: str | None = None) -> tuple[dict, int | None]:
    """获取调用配置：优先多渠道，回退旧单渠道。

    Args:
        user_key: 用户标识，优先使用用户私有通道，降级到全局通道

    Returns:
        (config_dict, channel_id_or_None)
        config_dict 含 base_url, api_key, model, temperature
    """
    channel = channel_service.select_channel(db, model=model, user_key=user_key)
    if channel and channel.api_key:
        return (
            {
                "base_url": channel.base_url,
                "api_key": channel.api_key,
                "model": model or channel.default_model,
                "temperature": channel.temperature,
                "vision_model": channel.vision_model,
            },
            channel.id,
        )
    # 回退旧配置
    try:
        cfg = require_ai_config(db)
        return (
            {
                "base_url": cfg["base_url"],
                "api_key": cfg["api_key"],
                "model": model or cfg["model"],
                "temperature": cfg["temperature"],
                "vision_model": cfg.get("vision_model", ""),
            },
            None,
        )
    except AiConfigError as e:
        raise AiGatewayError(str(e)) from e


async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    usage_collector: list | None = None,
    info_collector: dict | None = None,
    tool_calls_collector: list | None = None,
    db: Session | None = None,
    user_key: str | None = None,
):
    """流式对话：逐段产出文本增量；支持多渠道故障转移；自动记录调用日志。

    Args:
        tools: 可选，OpenAI 兼容的 function calling tools 定义列表。
            传入后 payload 会透传 tools，响应中的 tool_calls 会被流式累积。
        tool_choice: 可选，"auto" / "none" / {"type":"function","function":{"name":"xxx"}}。
        usage_collector: 可选 list，若传入则会把 LLM 返回的 usage 信息追加进去。
        info_collector: 可选 dict，若传入则会在调用结束后写入模型、渠道、token、费用等信息。
            包含：model, channel_name, channel_id, prompt_tokens, completion_tokens, total_tokens, cost_estimate, duration_ms, status
        tool_calls_collector: 可选 list，若传入则会把累积完成的 tool_calls 列表 append 进去。
            每个元素格式：{"id": str, "type": "function", "function": {"name": str, "arguments": str}}
        db: 可选数据库会话，用于渠道选择和统计记录；不传则自动创建。
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    # 未显式传入 user_key 时，从 contextvar 读取当前登录用户
    if user_key is None:
        user_key = get_current_user_key()

    # 读取功能级配置（ai.func.{function_type}.*），覆盖默认通道/模型/温度
    func_channel_id: int | None = None
    func_model: str | None = None
    func_temperature: float | None = None
    func_type = call_logger.get_function_type()
    if func_type and func_type != "other" and user_key:
        try:
            user_db = user_db_manager.get_session(user_key)
            from ..models import UserSetting
            from sqlalchemy import select
            rows = user_db.execute(
                select(UserSetting.key, UserSetting.value).where(
                    UserSetting.key.like(f"ai.func.{func_type}.%")
                )
            ).all()
            for k, v in rows:
                field = k[len(f"ai.func.{func_type}."):]
                if field == "channel_id" and v:
                    func_channel_id = int(v)
                elif field == "model" and v:
                    func_model = v
                elif field == "temperature" and v:
                    func_temperature = float(v)
            user_db.close()
        except Exception as e:
            logger.debug("读取功能配置失败 func=%s: %s", func_type, e)

    # 功能配置覆盖默认值
    if func_model and model is None:
        model = func_model
    if func_temperature and temperature is None:
        temperature = func_temperature

    # 调用记录相关状态
    t0 = time.monotonic()
    full_output: list[str] = []
    final_usage: dict = {}
    used_model = ""
    used_channel_id: int | None = None
    used_channel_name = ""
    call_success = False
    call_error = ""
    # tool_calls 流式累积器：key=index, value=tool_call dict
    tool_calls_acc: dict[int, dict] = {}

    try:
        # 收集本次尝试过的渠道，用于故障转移时排除
        tried_channel_ids: set[int] = set()
        last_error: Exception | None = None

        for failover in range(MAX_CHANNEL_FAILOVER + 1):
            # 选择渠道（排除已失败的）
            try:
                cfg, channel_id = _get_channel_config_with_exclusion(
                    db, model=model, exclude_ids=tried_channel_ids, user_key=user_key,
                    preferred_channel_id=func_channel_id,
                )
            except AiGatewayError:
                if last_error:
                    raise last_error
                raise

            if channel_id is not None:
                tried_channel_ids.add(channel_id)
                used_channel_id = channel_id
                ch = channel_service.get_channel(db, channel_id)
                if ch:
                    used_channel_name = ch.name

            used_model = cfg["model"]

            payload = {
                "model": cfg["model"],
                "messages": messages,
                "temperature": cfg["temperature"] if temperature is None else temperature,
                "stream": True,
            }
            if tools is not None:
                payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

            # 单渠道内重试
            channel_error: Exception | None = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    async with _build_client(cfg["base_url"], cfg["api_key"]) as client:
                        async with client.stream("POST", "/chat/completions", json=payload) as resp:
                            if resp.status_code != 200:
                                body = (await resp.aread()).decode("utf-8", "replace")[:500]
                                if _is_retryable(resp.status_code) and attempt < MAX_RETRIES:
                                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                                    logger.warning(
                                        "渠道#%s %s，%.1fs 后重试 (%d/%d)",
                                        channel_id, resp.status_code, delay, attempt + 1, MAX_RETRIES,
                                    )
                                    await asyncio.sleep(delay)
                                    channel_error = AiGatewayError(f"LLM 接口返回 {resp.status_code}: {body}")
                                    continue
                                channel_error = AiGatewayError(f"LLM 接口返回 {resp.status_code}: {body}")
                                break

                            # 成功：逐行 yield
                            tokens_used = 0
                            async for line in resp.aiter_lines():
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    # 成功完成，记录统计
                                    call_success = True
                                    if channel_id is not None:
                                        channel_service.record_call(
                                            db, channel_id, success=True, tokens=tokens_used
                                        )
                                    # 记录调用日志（在 finally 中统一处理，这里标记成功）
                                    return
                                try:
                                    chunk = json.loads(data)
                                except json.JSONDecodeError:
                                    continue
                                if usage_collector is not None and "usage" in chunk:
                                    usage_collector.append(chunk["usage"])
                                    final_usage = chunk["usage"]
                                    tokens_used += chunk["usage"].get("total_tokens", 0)
                                choices = chunk.get("choices") or []
                                if not choices:
                                    continue
                                delta = choices[0].get("delta") or {}
                                text = delta.get("content")
                                if text:
                                    full_output.append(text)
                                    yield text
                                # 流式累积 tool_calls（arguments 是增量拼接的）
                                delta_tool_calls = delta.get("tool_calls")
                                if delta_tool_calls:
                                    for tc_delta in delta_tool_calls:
                                        idx = tc_delta.get("index", 0)
                                        if idx not in tool_calls_acc:
                                            tool_calls_acc[idx] = {
                                                "id": "",
                                                "type": "function",
                                                "function": {"name": "", "arguments": ""},
                                            }
                                        if tc_delta.get("id"):
                                            tool_calls_acc[idx]["id"] = tc_delta["id"]
                                        if tc_delta.get("type"):
                                            tool_calls_acc[idx]["type"] = tc_delta["type"]
                                        func_delta = tc_delta.get("function") or {}
                                        if func_delta.get("name"):
                                            tool_calls_acc[idx]["function"]["name"] = func_delta["name"]
                                        if func_delta.get("arguments"):
                                            tool_calls_acc[idx]["function"]["arguments"] += func_delta["arguments"]
                            # 正常结束（无 [DONE] 标记的情况）
                            call_success = True
                            if channel_id is not None:
                                channel_service.record_call(
                                    db, channel_id, success=True, tokens=tokens_used
                                )
                            return
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    if attempt < MAX_RETRIES:
                        delay = RETRY_DELAY_BASE * (2 ** attempt)
                        logger.warning(
                            "渠道#%s 网络错误，%.1fs 后重试 (%d/%d): %s",
                            channel_id, delay, attempt + 1, MAX_RETRIES, e,
                        )
                        await asyncio.sleep(delay)
                        channel_error = e
                        continue
                    channel_error = AiGatewayError(f"AI 网关网络错误：{e}")
                    break

            # 渠道失败，记录并尝试故障转移
            if channel_error:
                last_error = channel_error
                call_error = str(channel_error)
                if channel_id is not None:
                    err_msg = str(channel_error)[:500]
                    channel_service.record_call(db, channel_id, success=False, error=err_msg)
                if failover < MAX_CHANNEL_FAILOVER:
                    logger.warning("渠道#%s 失败，尝试故障转移 (%d/%d)", channel_id, failover + 1, MAX_CHANNEL_FAILOVER)
                    continue
                break

        if last_error:
            call_error = str(last_error)
            raise AiGatewayError(f"AI 网关所有渠道均失败：{last_error}")
    finally:
        # 记录调用日志（无论成功失败）
        try:
            duration_ms = int((time.monotonic() - t0) * 1000)
            output_text = "".join(full_output)
            # 整理累积的 tool_calls（按 index 排序），传递给调用方
            final_tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
            if tool_calls_collector is not None:
                tool_calls_collector.extend(final_tool_calls)
            prompt_tokens = final_usage.get("prompt_tokens", 0)
            completion_tokens = final_usage.get("completion_tokens", 0)
            total_tokens = final_usage.get("total_tokens", 0) or (prompt_tokens + completion_tokens)

            # 估算 token（如果服务商未返回 usage）
            if total_tokens == 0:
                # 粗略估算：中文约 1.5 字符/token，英文约 4 字符/token
                input_chars = sum(len(m.get("content", "")) for m in messages if isinstance(m, dict))
                prompt_tokens = max(1, int(input_chars / 2.5))
                completion_tokens = max(1, int(len(output_text) / 2.5))
                total_tokens = prompt_tokens + completion_tokens

            # 功能类型兜底：调用方未显式设置时根据 prompt 关键词推断
            _cur_ft = call_logger.get_function_type()
            _inferred = _infer_function_type(messages) if _cur_ft == "other" else None
            _ft_token = None
            if _inferred and _inferred != "other":
                _ft_token = call_logger.set_function_type(_inferred)
            try:
                call_logger.record_call(
                    model=used_model,
                    messages=messages,
                    output=output_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    channel_id=used_channel_id,
                    channel_name=used_channel_name,
                    status="success" if call_success else "failed",
                    error_message=call_error,
                    duration_ms=duration_ms,
                    db=db,
                )
            finally:
                if _ft_token is not None:
                    call_logger.reset_function_type(_ft_token)

            # 写入 info_collector（用于消息显示token、模型、费用）
            if info_collector is not None:
                try:
                    from .call_logger import estimate_cost
                    cost = estimate_cost(used_model, prompt_tokens, completion_tokens)
                    info_collector.update({
                        "model": used_model,
                        "channel_name": used_channel_name,
                        "channel_id": used_channel_id,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "cost_estimate": cost,
                        "duration_ms": duration_ms,
                        "status": "success" if call_success else "failed",
                    })
                except Exception as e:
                    logger.error("写入 info_collector 失败: %s", e)
        except Exception as e:
            logger.error("记录 AI 调用日志失败: %s", e, exc_info=True)
        if close_db:
            db.close()


def _get_channel_config_with_exclusion(
    db: Session, *, model: str | None = None, exclude_ids: set[int] | None = None, user_key: str | None = None,
    preferred_channel_id: int | None = None,
) -> tuple[dict, int | None]:
    """选择渠道时排除指定 ID（故障转移用）。优先使用功能配置指定的通道。"""
    from ..models import AiChannel
    from sqlalchemy import select

    # 优先使用功能配置指定的通道
    if preferred_channel_id is not None and preferred_channel_id not in (exclude_ids or set()):
        ch = channel_service.get_channel(db, preferred_channel_id)
        if ch and ch.enabled and ch.api_key and ch.status != "error":
            return (
                {
                    "base_url": ch.base_url,
                    "api_key": ch.api_key,
                    "model": model or ch.default_model,
                    "temperature": ch.temperature,
                    "vision_model": ch.vision_model,
                },
                ch.id,
            )

    if not exclude_ids:
        return _get_channel_config(db, model=model, user_key=user_key)

    # 手动选择：排除指定渠道 + 排除 status=error 的渠道
    # 用户隔离：优先用户私有通道 + 全局通道
    channels = channel_service.list_channels(db, only_enabled=True, user_key=user_key, scope="all")
    available = [ch for ch in channels if ch.id not in (exclude_ids or set()) and ch.status != "error"]
    if not available:
        # 没有更多健康渠道，回退旧配置
        try:
            cfg = require_ai_config(db)
            return (
                {
                    "base_url": cfg["base_url"],
                    "api_key": cfg["api_key"],
                    "model": model or cfg["model"],
                    "temperature": cfg["temperature"],
                    "vision_model": cfg.get("vision_model", ""),
                },
                None,
            )
        except AiConfigError as e:
            raise AiGatewayError(str(e)) from e

    # 从可用渠道中按优先级+权重选一个
    import random
    from collections import defaultdict
    groups = defaultdict(list)
    for ch in available:
        groups[ch.priority].append(ch)
    top_priority = min(groups.keys())
    candidates = groups[top_priority]
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        total_weight = sum(max(1, ch.weight) for ch in candidates)
        pick = random.uniform(0, total_weight)
        cumulative = 0
        chosen = candidates[-1]
        for ch in candidates:
            cumulative += max(1, ch.weight)
            if pick <= cumulative:
                chosen = ch
                break

    return (
        {
            "base_url": chosen.base_url,
            "api_key": chosen.api_key,
            "model": model or chosen.default_model,
            "temperature": chosen.temperature,
            "vision_model": chosen.vision_model,
        },
        chosen.id,
    )


async def chat_once(messages: list[dict], **kwargs) -> str:
    """非流式单次调用（用于出题/判定等短任务）。"""
    parts = []
    async for part in chat_stream(messages, **kwargs):
        parts.append(part)
    return "".join(parts)


async def chat_once_with_usage(messages: list[dict], **kwargs) -> tuple[str, dict]:
    """非流式单次调用，同时返回文本和 token 用量统计。"""
    parts = []
    usage_collector: list = []
    async for part in chat_stream(messages, usage_collector=usage_collector, **kwargs):
        parts.append(part)
    text = "".join(parts)
    usage = usage_collector[-1] if usage_collector else {}
    return text, usage


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    tool_choice: str | dict = "auto",
    model: str | None = None,
    temperature: float | None = None,
    db: Session | None = None,
    user_key: str | None = None,
) -> dict:
    """带 Function Calling 的单次调用，返回结构化结果。

    用于出题、知识点细化等需要严格结构化输出的场景。
    相比 chat_once + 纯文本 JSON，格式可靠性从 ~70% 提升到 99.9%+，
    且不生成无效 token，输出 token 降低 15-40%。

    Args:
        messages: 对话消息列表
        tools: OpenAI 兼容的 function definitions 列表
        tool_choice: "auto" / "none" / {"type":"function","function":{"name":"xxx"}}
        model: 覆盖默认模型
        temperature: 覆盖默认温度
        db: 数据库会话

    Returns:
        dict: {
            "content": str,           # 模型返回的纯文本（可能为空）
            "tool_calls": list[dict], # 工具调用列表，每个含 id/type/function
            "usage": dict,            # token 用量
        }
        每个 tool_call 的 function.arguments 是 JSON 字符串，调用方需 json.loads。
    """
    parts: list[str] = []
    tool_calls_collector: list[dict] = []
    usage_collector: list[dict] = []
    async for text in chat_stream(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        model=model,
        temperature=temperature,
        usage_collector=usage_collector,
        tool_calls_collector=tool_calls_collector,
        db=db,
        user_key=user_key,
    ):
        parts.append(text)
    return {
        "content": "".join(parts),
        "tool_calls": tool_calls_collector,
        "usage": usage_collector[-1] if usage_collector else {},
    }


def extract_tool_arguments(result: dict, tool_index: int = 0) -> dict:
    """从 chat_with_tools 返回值中提取指定 tool_call 的 arguments 并解析为 dict。

    Args:
        result: chat_with_tools 的返回值
        tool_index: 第几个 tool_call（默认第一个）

    Returns:
        dict: 解析后的 arguments。如果没有 tool_call 或解析失败，返回空 dict。
    """
    tool_calls = result.get("tool_calls") or []
    if tool_index >= len(tool_calls):
        return {}
    func = tool_calls[tool_index].get("function") or {}
    args_str = func.get("arguments", "")
    if not args_str:
        return {}
    try:
        return json.loads(args_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning("extract_tool_arguments: JSON 解析失败，arguments=%s", args_str[:200])
        return {}
