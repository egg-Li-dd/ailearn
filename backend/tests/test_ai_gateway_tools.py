"""ai_gateway Function Calling 单元测试。

验证：
1. 流式 tool_calls 响应的 arguments 增量拼接正确
2. 多个 tool_calls 按 index 排序
3. 无 tool_calls 时返回空列表
4. payload 正确透传 tools / tool_choice
5. extract_tool_arguments 正确解析
"""
import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_gateway import chat_with_tools, extract_tool_arguments


# ---------------------------------------------------------------------------
# 辅助：构造模拟的 SSE 流式响应
# ---------------------------------------------------------------------------

def _make_sse_chunks(*payloads: dict) -> list[str]:
    """把多个 JSON payload 转为 SSE data 行，末尾追加 [DONE]。"""
    lines = [f"data: {json.dumps(p, ensure_ascii=False)}" for p in payloads]
    lines.append("data: [DONE]")
    return lines


def _make_mock_response(sse_lines: list[str]) -> MagicMock:
    """构造模拟的 httpx 响应对象，支持 aiter_lines 异步迭代。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    async def _aiter_lines():
        for line in sse_lines:
            yield line

    mock_resp.aiter_lines = _aiter_lines
    return mock_resp


def _make_mock_client(mock_resp: MagicMock) -> MagicMock:
    """构造模拟的 httpx.AsyncClient，支持异步上下文管理器 + stream。"""
    mock_client = MagicMock()
    # httpx.AsyncClient 本身是异步上下文管理器
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    # client.stream(...) 返回的对象也是异步上下文管理器
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=ctx)
    return mock_client


def _patch_gateway_deps(mock_client: MagicMock):
    """返回一组 patch，mock 掉网关的所有外部依赖。"""
    mock_db = MagicMock()
    return [
        patch("app.services.ai_gateway.SessionLocal", return_value=mock_db),
        patch(
            "app.services.ai_gateway._get_channel_config",
            return_value=(
                {
                    "base_url": "http://mock.test/v1",
                    "api_key": "mock-key",
                    "model": "mock-model",
                    "temperature": 0.7,
                    "vision_model": "",
                },
                1,
            ),
        ),
        patch("app.services.ai_gateway._build_client", return_value=mock_client),
        patch("app.services.ai_gateway.channel_service.record_call"),
        patch("app.services.ai_gateway.call_logger.record_call"),
    ]


# ---------------------------------------------------------------------------
# 测试：单个 tool call
# ---------------------------------------------------------------------------

class TestSingleToolCall:
    @pytest.mark.anyio
    async def test_arguments_incremental_concat(self):
        """arguments 分多块传输时，应正确拼接为完整 JSON。"""
        # 第一块：tool_call 元信息 + arguments 前半
        chunk1 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "generate_quiz",
                                    "arguments": '{"question":"二叉树的',
                                },
                            }
                        ]
                    }
                }
            ]
        }
        # 第二块：仅 arguments 增量
        chunk2 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '层序遍历用什么实现？","answer":"队列"}'},
                            }
                        ]
                    }
                }
            ]
        }

        sse_lines = _make_sse_chunks(chunk1, chunk2)
        mock_resp = _make_mock_response(sse_lines)
        mock_client = _make_mock_client(mock_resp)

        patches = _patch_gateway_deps(mock_client)
        for p in patches:
            p.start()
        try:
            result = await chat_with_tools(
                [{"role": "user", "content": "出一道题"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "generate_quiz",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )
        finally:
            for p in patches:
                p.stop()

        # 验证
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_abc123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "generate_quiz"

        # arguments 应被正确拼接为合法 JSON
        args = json.loads(tc["function"]["arguments"])
        assert args["question"] == "二叉树的层序遍历用什么实现？"
        assert args["answer"] == "队列"

    @pytest.mark.anyio
    async def test_content_and_tool_calls_coexist(self):
        """模型同时返回文本和 tool_call 时，两者都应被捕获。"""
        chunk = {
            "choices": [
                {
                    "delta": {
                        "content": "好的，我来出题。",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_xyz",
                                "type": "function",
                                "function": {
                                    "name": "generate_quiz",
                                    "arguments": '{"q":"t"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

        sse_lines = _make_sse_chunks(chunk)
        mock_resp = _make_mock_response(sse_lines)
        mock_client = _make_mock_client(mock_resp)

        patches = _patch_gateway_deps(mock_client)
        for p in patches:
            p.start()
        try:
            result = await chat_with_tools(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
            )
        finally:
            for p in patches:
                p.stop()

        assert result["content"] == "好的，我来出题。"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["function"]["name"] == "generate_quiz"


# ---------------------------------------------------------------------------
# 测试：多个 tool call
# ---------------------------------------------------------------------------

class TestMultipleToolCalls:
    @pytest.mark.anyio
    async def test_multiple_tool_calls_sorted_by_index(self):
        """多个 tool_calls 乱序到达时，应按 index 排序输出。"""
        # 先到 index=1，再到 index=0（乱序）
        chunk1 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": "func_b", "arguments": '{"b":2}'},
                            }
                        ]
                    }
                }
            ]
        }
        chunk2 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "func_a", "arguments": '{"a":1}'},
                            }
                        ]
                    }
                }
            ]
        }

        sse_lines = _make_sse_chunks(chunk1, chunk2)
        mock_resp = _make_mock_response(sse_lines)
        mock_client = _make_mock_client(mock_resp)

        patches = _patch_gateway_deps(mock_client)
        for p in patches:
            p.start()
        try:
            result = await chat_with_tools(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
            )
        finally:
            for p in patches:
                p.stop()

        assert len(result["tool_calls"]) == 2
        # 按 index 排序：index=0 在前，index=1 在后
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["function"]["name"] == "func_a"
        assert result["tool_calls"][1]["id"] == "call_2"
        assert result["tool_calls"][1]["function"]["name"] == "func_b"


# ---------------------------------------------------------------------------
# 测试：无 tool call
# ---------------------------------------------------------------------------

class TestNoToolCall:
    @pytest.mark.anyio
    async def test_no_tool_calls_returns_empty_list(self):
        """模型只返回文本、不调用工具时，tool_calls 应为空列表。"""
        chunk = {
            "choices": [
                {"delta": {"content": "这是一个纯文本回复。"}}
            ]
        }

        sse_lines = _make_sse_chunks(chunk)
        mock_resp = _make_mock_response(sse_lines)
        mock_client = _make_mock_client(mock_resp)

        patches = _patch_gateway_deps(mock_client)
        for p in patches:
            p.start()
        try:
            result = await chat_with_tools(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
            )
        finally:
            for p in patches:
                p.stop()

        assert result["content"] == "这是一个纯文本回复。"
        assert result["tool_calls"] == []


# ---------------------------------------------------------------------------
# 测试：payload 透传
# ---------------------------------------------------------------------------

class TestPayloadPassthrough:
    @pytest.mark.anyio
    async def test_tools_and_tool_choice_in_payload(self):
        """请求 payload 应正确包含 tools 和 tool_choice。"""
        chunk = {"choices": [{"delta": {"content": "ok"}}]}
        sse_lines = _make_sse_chunks(chunk)
        mock_resp = _make_mock_response(sse_lines)
        mock_client = _make_mock_client(mock_resp)

        captured_payload = {}

        # 拦截 _build_client 返回的 client，检查 stream 调用的 payload
        original_stream = mock_client.stream

        def capture_stream(method, url, json=None, **kwargs):
            captured_payload.update(json or {})
            return original_stream(method, url, json=json, **kwargs)

        mock_client.stream = MagicMock(side_effect=capture_stream)

        patches = _patch_gateway_deps(mock_client)
        for p in patches:
            p.start()
        try:
            await chat_with_tools(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "test_func", "parameters": {}}}],
                tool_choice={"type": "function", "function": {"name": "test_func"}},
            )
        finally:
            for p in patches:
                p.stop()

        assert "tools" in captured_payload
        assert len(captured_payload["tools"]) == 1
        assert captured_payload["tools"][0]["function"]["name"] == "test_func"
        assert "tool_choice" in captured_payload
        assert captured_payload["tool_choice"]["function"]["name"] == "test_func"


# ---------------------------------------------------------------------------
# 测试：extract_tool_arguments
# ---------------------------------------------------------------------------

class TestExtractToolArguments:
    def test_extract_first_tool_call(self):
        """应正确提取第一个 tool_call 的 arguments 并解析为 dict。"""
        result = {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "generate_quiz",
                        "arguments": '{"question":"test","answer":"A","difficulty":3}',
                    },
                }
            ],
        }
        args = extract_tool_arguments(result)
        assert args["question"] == "test"
        assert args["answer"] == "A"
        assert args["difficulty"] == 3

    def test_extract_specific_index(self):
        """应支持提取指定 index 的 tool_call。"""
        result = {
            "content": "",
            "tool_calls": [
                {"function": {"arguments": '{"a":1}'}},
                {"function": {"arguments": '{"b":2}'}},
            ],
        }
        args = extract_tool_arguments(result, tool_index=1)
        assert args["b"] == 2

    def test_no_tool_calls_returns_empty(self):
        """没有 tool_calls 时返回空 dict。"""
        assert extract_tool_arguments({"content": "hi", "tool_calls": []}) == {}
        assert extract_tool_arguments({"content": "hi"}) == {}

    def test_invalid_json_returns_empty(self):
        """arguments 不是合法 JSON 时返回空 dict，不抛异常。"""
        result = {
            "tool_calls": [
                {"function": {"arguments": "not valid json{{{"}}
            ]
        }
        assert extract_tool_arguments(result) == {}

    def test_empty_arguments_returns_empty(self):
        """arguments 为空字符串时返回空 dict。"""
        result = {"tool_calls": [{"function": {"arguments": ""}}]}
        assert extract_tool_arguments(result) == {}
