"""手写答案批改服务（多模态 AI）。

职责：
- 接收题目信息 + 手写答案图片（base64）
- 构建多模态 messages，调用视觉模型识别手写并批改
- 返回结构化批改结果（与现有判卷格式统一）

批改结果格式：
{
  "correct": bool,
  "score": int,
  "max_points": int,
  "recognized_text": str,       # AI 识别的手写文字
  "point_results": [             # 得分点明细
    {"point": str, "got": bool, "score": int, "max_score": int, "feedback": str}
  ],
  "error_analysis": str,         # 错误分析
  "explanation": str,            # 参考答案/解析
}
"""
import base64
import json
import logging

import time

from sqlalchemy.orm import Session

from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_once
from . import experiment_service

logger = logging.getLogger("ailearn.handwrite_grading")

# 多模态视觉模型（可通过配置覆盖）
DEFAULT_VISION_MODEL = "qwen-vl-max"



def _build_grading_messages_v1(
    question: str,
    reference_answer: str,
    image_data: str,
    points: list[dict] | None = None,
) -> list[dict]:
    """旧版 v1：单 user + 完整多行 JSON 示例（A/B 对照组）。

    与 v2（system+user 分离 + 字段定义表）对比：
    - v1: 单 user 消息，角色+题目+参考答案+批改要求+完整多行JSON示例全部混在文本中
    - v2: system 独立放角色+字段定义表+规则，user 仅参数JSON+图片，预计节省 token 30%
    """
    points_text = ""
    if points:
        points_text = "\n得分点：\n" + "\n".join(
            f"- {p.get('point', '')}（{p.get('score', 1)}分）" for p in points
        )

    prompt = (
        "你是严格的阅卷老师。请识别图片中的手写答案并批改。\n\n"
        f"题目：{question}\n"
        f"参考答案：{reference_answer}\n"
        f"{points_text}\n\n"
        "请先完整识别手写文字（中文、英文、数字、公式符号），然后逐得分点评分。\n"
        "返回严格 JSON（不要任何其他文字、不要代码块）：\n"
        "{\n"
        '  "recognized_text": "识别的手写答案完整文本",\n'
        '  "point_results": [\n'
        '    {"point": "得分点描述", "got": true/false, "score": 实际得分, "max_score": 满分, "feedback": "评分说明"}\n'
        "  ],\n"
        '  "total_score": 总得分,\n'
        '  "max_points": 满分,\n'
        '  "error_analysis": "错误分析",\n'
        '  "explanation": "完整参考答案和解析"\n'
        "}\n\n"
        "规则：无法辨认或为空得0分；输出紧凑JSON（单行无缩进）。"
    )
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data}},
            ],
        }
    ]


def _build_grading_system() -> str:
    """构建批改 system 消息（角色 + 字段定义表 + 规则）。

    优化策略：
    - system 独立放角色定义、字段定义表（代替完整多行JSON示例）、合并规则段
    - 预计节省 prompt token 约 30%
    """
    return (
        "你是严格的阅卷老师。识别图片中的手写答案并批改。\n"
        "输出严格 JSON，不要任何其他文字、不要代码块。\n\n"
        "字段定义：\n"
        "- recognized_text: string 识别的手写答案完整文本\n"
        "- point_results: array 得分点明细，每项含：\n"
        "  - point: string 得分点描述\n"
        "  - got: bool 是否覆盖该得分点\n"
        "  - score: int 实际得分\n"
        "  - max_score: int 该点满分\n"
        "  - feedback: string 评分说明\n"
        "- total_score: int 总得分\n"
        "- max_points: int 满分\n"
        "- error_analysis: string 错误分析\n"
        "- explanation: string 完整参考答案和解析\n\n"
        "规则：\n"
        "- 先完整识别手写文字（中文、英文、数字、公式符号）\n"
        "- 逐得分点评分，判断是否覆盖该点\n"
        "- 无法辨认或为空得 0 分\n"
        "- 输出紧凑 JSON（单行无缩进）"
    )


def _build_grading_user_text(
    question: str,
    reference_answer: str,
    points: list[dict] | None = None,
) -> str:
    """构建批改 user 文本内容（参数 JSON，不含图片）。"""
    user_data: dict = {
        "question": question,
        "reference_answer": reference_answer,
    }
    if points:
        user_data["points"] = [
            {"point": p.get("point", ""), "score": p.get("score", 1)}
            for p in points
        ]
    return json.dumps(user_data, ensure_ascii=False)


async def grade_handwrite(
    question: str,
    reference_answer: str,
    image_base64: str,
    *,
    points: list[dict] | None = None,
    max_points: int = 10,
    model: str | None = None,
    db: Session | None = None,
) -> dict:
    """批改手写答案。

    Args:
        question: 题目题干
        reference_answer: 参考答案
        image_base64: 手写答案图片的 base64 编码（不含 data:image/...;base64, 前缀）
        points: 得分点列表，如 [{"point": "使用队列", "score": 3}, ...]
        max_points: 满分（如果没有 points 则用这个）
        model: 多模态模型名，默认 qwen-vl-max

    Returns:
        结构化批改结果 dict

    Raises:
        AiGatewayError: AI 调用失败
        ValueError: 图片数据无效或 AI 返回格式异常
    """
    if not image_base64 or not image_base64.strip():
        raise ValueError("手写答案图片为空")

    # 验证 base64 并构建 data URL
    try:
        # 如果已经带前缀，去掉
        if image_base64.startswith("data:"):
            image_data = image_base64
        else:
            image_data = f"data:image/png;base64,{image_base64}"
        # 验证 base64 可解码
        pure_b64 = image_data.split(",", 1)[1] if "," in image_data else image_data
        base64.b64decode(pure_b64, validate=True)
    except Exception as e:
        raise ValueError(f"图片 base64 解码失败: {e}") from e

    # A/B 实验分桶
    _exp = experiment_service.get_experiment(db, "handwrite_prompt_v2") if db else None
    _variant = experiment_service.assign_variant(_exp, f"q_{hash(question) % 10000}") if _exp else None
    _exp_start = time.monotonic()

    if _variant == "control":
        messages = _build_grading_messages_v1(question, reference_answer, image_data, points)
    else:
        # 多模态 messages：system 独立 + user(content 数组含文本和图片)
        messages = [
            {"role": "system", "content": _build_grading_system()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _build_grading_user_text(question, reference_answer, points)},
                    {"type": "image_url", "image_url": {"url": image_data}},
                ],
            },
        ]

    try:
        set_function_type("handwrite")
        raw = await chat_once(
            messages,
            model=model or DEFAULT_VISION_MODEL,
            temperature=0.1,
        )
    except AiGatewayError as e:
        logger.error("手写批改 AI 调用失败: %s", e)
        if _exp and _variant and db:
            _exp_duration = int((time.monotonic() - _exp_start) * 1000)
            experiment_service.record_event(_exp, _variant, f"q_{hash(question) % 10000}", "handwrite", {
                "format_valid": False,
                "duration_ms": _exp_duration,
            })
        raise

    # 解析 AI 返回的 JSON
    try:
        # 清理可能的 markdown 代码块
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("手写批改 AI 返回格式异常: %s\n原始返回: %s", e, raw[:500])
        raise ValueError(f"AI 批改返回格式异常: {e}") from e

    # 归一化结果
    normalized = _normalize_result(result, question, reference_answer, points, max_points)
    # 记录 A/B 实验事件
    if _exp and _variant and db:
        _exp_duration = int((time.monotonic() - _exp_start) * 1000)
        experiment_service.record_event(_exp, _variant, f"q_{hash(question) % 10000}", "handwrite", {
            "format_valid": True,
            "duration_ms": _exp_duration,
        })

    return normalized


def _normalize_result(
    result: dict,
    question: str,
    reference_answer: str,
    points: list[dict] | None,
    default_max_points: int,
) -> dict:
    """归一化 AI 返回的批改结果，确保字段完整。"""
    point_results = result.get("point_results", [])
    if not isinstance(point_results, list):
        point_results = []

    # 计算总分
    total_score = result.get("total_score", 0)
    if not isinstance(total_score, (int, float)):
        total_score = sum(p.get("score", 0) for p in point_results if isinstance(p, dict))
    total_score = int(total_score)

    max_points = result.get("max_points", default_max_points)
    if not isinstance(max_points, (int, float)):
        max_points = default_max_points
    max_points = int(max_points)

    # 如果有预定义得分点，补全缺失的得分点
    if points:
        existing_points = {p.get("point", "") for p in point_results if isinstance(p, dict)}
        for pt in points:
            if pt.get("point", "") not in existing_points:
                point_results.append({
                    "point": pt.get("point", ""),
                    "got": False,
                    "score": 0,
                    "max_score": pt.get("score", 1),
                    "feedback": "未覆盖该得分点",
                })

    # 确保每个得分点字段完整
    normalized_points = []
    for p in point_results:
        if not isinstance(p, dict):
            continue
        normalized_points.append({
            "point": p.get("point", ""),
            "got": bool(p.get("got", False)),
            "score": int(p.get("score", 0)),
            "max_score": int(p.get("max_score", 1)),
            "feedback": p.get("feedback", ""),
        })

    correct = total_score >= max_points  # 全部得分才算正确

    return {
        "correct": correct,
        "score": total_score,
        "max_points": max_points,
        "recognized_text": result.get("recognized_text", ""),
        "point_results": normalized_points,
        "error_analysis": result.get("error_analysis", ""),
        "explanation": result.get("explanation", reference_answer),
        "question": question,
    }
