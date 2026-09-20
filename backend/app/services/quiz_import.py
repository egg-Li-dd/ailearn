"""题目导入与结构化引擎（Phase 1）。

功能：
1. 从原始文本（粘贴/图片OCR/PDF提取）AI 解析为结构化题目
2. AI 自动标注：关联知识树节点、难度、题型、考频
3. AI 生成步骤化解析、思路地图、易错点
4. 标准化保存为 QuizQuestion（v2.0 契约扩展）

设计要点：
- 用 Function Calling 保证结构化输出可靠性（参考 chat_with_tools）
- 解析+标注合并为一次 AI 调用，解析生成为另一次
- 支持批量导入，每题独立失败不影响其他
- 所有公式保留 LaTeX 格式（$...$ / $$...$$）
"""
import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, QuizQuestion
from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_with_tools, extract_tool_arguments
from .quiz_contract import (
    SCHEMA_VERSION,
    QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE,
    QTYPE_FILL_SINGLE, QTYPE_SHORT,
    normalize_payload,
)

logger = logging.getLogger("ailearn.quiz_import")

# 知识点节点缓存（批量导入时避免重复查询）
_node_cache: dict[str, Any] = {"nodes": None, "timestamp": 0}
_NODE_CACHE_TTL = 60  # 缓存60秒

# 导入来源标记
SOURCE_IMPORT = "import"
SOURCE_AI_GENERATED = "ai_generated"
SOURCE_MANUAL = "manual"

# 题型映射（AI 输出 → 内部题型）
_QTYPE_MAP = {
    "single_choice": QTYPE_SINGLE_CHOICE,
    "multiple_choice": QTYPE_MULTIPLE_CHOICE,
    "judge": QTYPE_JUDGE,
    "fill": QTYPE_FILL_SINGLE,
    "fill_blank": QTYPE_FILL_SINGLE,
    "short": QTYPE_SHORT,
    "calculation": QTYPE_SHORT,  # 计算题归为简答
    "essay": QTYPE_SHORT,
}


# ============================================================
# Prompt 模板
# ============================================================

_PARSE_SYSTEM_PROMPT = """你是一个考研数学题目结构化解析专家。你的任务是把用户提供的原始题目文本（可能来自粘贴、图片OCR、PDF提取，格式可能不规范）解析为标准结构化数据。

## 题型定义
- single_choice：单选题（有A/B/C/D等选项，只有一个正确答案）
- multiple_choice：多选题（有多个选项，有两个或以上正确答案）
- judge：判断题（正确/错误）
- fill：填空题（题干中有空格需要填写，用 ____ 或 ___ 表示）
- short：简答题/计算题（需要写出解答过程，无选项）

## 数学公式
所有数学公式必须保留 LaTeX 格式：
- 行内公式用 $...$ 包裹，如 $\\frac{a}{b}$
- 独立公式用 $$...$$ 包裹
- 不要把公式转成纯文本

## 解析规则
1. 题干(question)：去除题号、多余空白，保留完整题目描述
2. 选项(options)：如果有选项，提取为字符串数组，去除 A. B. 等前缀
3. 判断题 options 固定为 ["正确", "错误"]
4. 填空题题干中的空格用 ____ 表示（4个下划线）
5. 答案(correct_answer)：
   - 单选/多选：选项字母，如 "A" 或 "AC"
   - 判断："正确" 或 "错误"
   - 填空：答案文本，多空用 | 分隔
   - 简答/计算：最终答案或关键结论
6. 如果原文没有给出答案，correct_answer 设为空字符串 ""
7. difficulty：1-5，1最简单，5最难，根据题目复杂度和计算量判断
8. knowledge_hint：用一句话描述这道题考察的核心知识点，用于后续关联知识树

## 输出要求
必须调用 parse_question 函数返回结构化数据，不要输出额外文本。
"""


_ANALYSIS_SYSTEM_PROMPT = """你是一个考研数学资深辅导老师。请为给定的题目生成高质量的解析。

## 解析结构
1. analysis：步骤化解析，数组形式，每步包含：
   - step：步骤序号（从1开始）
   - text：该步骤的详细说明，包含公式推导
2. thought_map：思路要点，一句话概括解题的核心思路和关键突破口
3. error_tips：易错点提醒，说明这道题常见的错误、陷阱和注意事项

## 数学公式
所有公式用 LaTeX 格式：
- 行内公式 $...$
- 独立公式 $$...$$

## 要求
- 解析要详细但不啰嗦，每一步都要有明确的推导
- 思路要点要指出"为什么这么做"，而不只是"怎么做"
- 易错点要具体，针对这道题的陷阱，不要泛泛而谈
- 如果题目没有给出答案，先自行推导答案再写解析

必须调用 generate_analysis 函数返回结构化数据。
"""


# ============================================================
# Function Definitions（OpenAI 兼容格式）
# ============================================================

_PARSE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "parse_question",
        "description": "解析原始题目文本为结构化数据",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "题干（去除题号，保留LaTeX公式）"},
                "qtype": {
                    "type": "string",
                    "enum": ["single_choice", "multiple_choice", "judge", "fill", "short"],
                    "description": "题型",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "选项数组（单选/多选/判断需要，填空和简答为空数组）",
                },
                "correct_answer": {"type": "string", "description": "标准答案（无答案则为空字符串）"},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5, "description": "难度1-5"},
                "knowledge_hint": {"type": "string", "description": "考察的核心知识点描述"},
            },
            "required": ["question", "qtype", "options", "correct_answer", "difficulty", "knowledge_hint"],
        },
    },
}


_ANALYSIS_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "generate_analysis",
        "description": "为题目的生成步骤化解析、思路要点和易错点",
        "parameters": {
            "type": "object",
            "properties": {
                "analysis": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer", "description": "步骤序号"},
                            "text": {"type": "string", "description": "步骤详细说明"},
                        },
                        "required": ["step", "text"],
                    },
                    "description": "步骤化解析数组",
                },
                "thought_map": {"type": "string", "description": "思路要点（核心突破口）"},
                "error_tips": {"type": "string", "description": "易错点提醒"},
            },
            "required": ["analysis", "thought_map", "error_tips"],
        },
    },
}


# ============================================================
# 核心函数
# ============================================================

async def parse_question(raw_text: str, *, db: Session | None = None) -> dict[str, Any]:
    """AI 解析原始题目文本为结构化数据。

    Args:
        raw_text: 原始题目文本（粘贴/OCR/PDF提取）
        db: 数据库会话（用于 AI 网关日志）

    Returns:
        解析后的结构化数据：
        {
            "question": str,
            "qtype": str（内部题型）,
            "options": list[str],
            "correct_answer": str,
            "difficulty": int,
            "knowledge_hint": str,
        }

    Raises:
        AiGatewayError: AI 调用失败
        ValueError: 解析结果无效
    """
    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("题目文本为空")

    messages = [
        {"role": "system", "content": _PARSE_SYSTEM_PROMPT},
        {"role": "user", "content": f"请解析以下题目：\n\n{raw_text}"},
    ]

    set_function_type("quiz")
    result = await chat_with_tools(
        messages,
        tools=[_PARSE_TOOL_DEF],
        tool_choice={"type": "function", "function": {"name": "parse_question"}},
        temperature=0.1,  # 低温度保证解析稳定性
        db=db,
    )

    parsed = extract_tool_arguments(result)
    if not parsed:
        raise AiGatewayError("AI 解析失败：未返回结构化数据")

    # 题型映射
    qtype_raw = parsed.get("qtype", "short")
    qtype = _QTYPE_MAP.get(qtype_raw, QTYPE_SHORT)

    # 判断题默认选项
    options = parsed.get("options") or []
    if qtype == QTYPE_JUDGE and not options:
        options = ["正确", "错误"]

    return {
        "question": parsed.get("question", "").strip(),
        "qtype": qtype,
        "options": options,
        "correct_answer": parsed.get("correct_answer", "").strip(),
        "difficulty": max(1, min(5, int(parsed.get("difficulty", 3)))),
        "knowledge_hint": parsed.get("knowledge_hint", "").strip(),
    }


async def generate_analysis(
    question: str,
    qtype: str,
    options: list[str] | None = None,
    correct_answer: str = "",
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    """AI 生成题目的步骤化解析、思路要点和易错点。

    Args:
        question: 题干
        qtype: 题型
        options: 选项
        correct_answer: 标准答案
        db: 数据库会话

    Returns:
        {
            "analysis": [{"step": int, "text": str}, ...],
            "thought_map": str,
            "error_tips": str,
        }
    """
    # 组装题目全文
    parts = [f"【题干】{question}"]
    if options:
        opt_str = "\n".join(f"{chr(65+i)}. {opt}" for i, opt in enumerate(options))
        parts.append(f"【选项】\n{opt_str}")
    if correct_answer:
        parts.append(f"【答案】{correct_answer}")
    full_text = "\n\n".join(parts)

    messages = [
        {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": f"请为以下题目生成解析：\n\n{full_text}"},
    ]

    set_function_type("quiz")
    result = await chat_with_tools(
        messages,
        tools=[_ANALYSIS_TOOL_DEF],
        tool_choice={"type": "function", "function": {"name": "generate_analysis"}},
        temperature=0.3,
        db=db,
    )

    analysis_data = extract_tool_arguments(result)
    if not analysis_data:
        logger.warning("AI 解析生成失败，返回空解析")
        return {"analysis": [], "thought_map": "", "error_tips": ""}

    return {
        "analysis": analysis_data.get("analysis", []),
        "thought_map": analysis_data.get("thought_map", ""),
        "error_tips": analysis_data.get("error_tips", ""),
    }


def find_matching_node(knowledge_hint: str, db: Session) -> KnowledgeNode | None:
    """根据知识点描述在知识树中查找最匹配的节点。

    简单实现：用关键词匹配节点名称和摘要。
    后续可升级为向量语义检索。
    使用模块级缓存避免批量导入时重复查询。
    """
    if not knowledge_hint:
        return None

    # 提取关键词（简单分词：按空格、标点分割，取长度>=2的词）
    keywords = re.findall(r'[\u4e00-\u9fa5a-zA-Z]{2,}', knowledge_hint)
    if not keywords:
        return None

    # 从缓存或数据库获取所有 level=4 节点
    import time
    now = time.time()
    if _node_cache["nodes"] is not None and (now - _node_cache["timestamp"]) < _NODE_CACHE_TTL:
        nodes = _node_cache["nodes"]
    else:
        nodes = db.execute(
            select(KnowledgeNode).where(KnowledgeNode.level == 4)
        ).scalars().all()
        _node_cache["nodes"] = nodes
        _node_cache["timestamp"] = now

    # 在知识点节点中搜索匹配
    best_node = None
    best_score = 0

    for node in nodes:
        score = 0
        name = node.name or ""
        summary = node.summary or ""
        for kw in keywords:
            if kw in name:
                score += 3  # 名称匹配权重高
            if kw in summary:
                score += 1
        if score > best_score:
            best_score = score
            best_node = node

    # 最低匹配分数阈值
    if best_score >= 2:
        return best_node
    return None


def build_payload(parsed: dict[str, Any], analysis_data: dict[str, Any]) -> dict[str, Any]:
    """构建 v2.0 扩展格式的题目 payload。

    在标准 v2.0 契约基础上扩展：
    - analysis: 步骤化解析数组（原 v2.0 已有，这里填充结构化数据）
    - thought_map: 思路要点（扩展字段）
    - error_tips: 易错点（扩展字段）
    - source: 来源标记（扩展字段）
    - knowledge_hint: AI 识别的知识点描述（扩展字段）
    - exam_freq: 考频（扩展字段，暂默认3）
    - tags: 标签数组（扩展字段）
    """
    qtype = parsed["qtype"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": qtype,
        "question": parsed["question"],
        "options": parsed["options"] if parsed["options"] else None,
        "blanks": None,
        "correct_answer": parsed["correct_answer"] or None,
        "explanation": "",  # 兼容字段，详细解析在 analysis 中
        "analysis": analysis_data.get("analysis", []),
        "points": 1,
        # === 扩展字段 ===
        "thought_map": analysis_data.get("thought_map", ""),
        "error_tips": analysis_data.get("error_tips", ""),
        "source": SOURCE_IMPORT,
        "knowledge_hint": parsed.get("knowledge_hint", ""),
        "exam_freq": 3,  # 默认考频中等
        "tags": [],
        "imported_at": datetime.utcnow().isoformat(),
    }
    return normalize_payload(payload)


def save_question(
    parsed: dict[str, Any],
    analysis_data: dict[str, Any],
    node_id: int | None,
    db: Session,
) -> QuizQuestion:
    """保存题目到数据库。

    Args:
        parsed: 解析后的题目数据
        analysis_data: 解析数据
        node_id: 关联的知识树节点 ID（可为 None）
        db: 数据库会话

    Returns:
        保存后的 QuizQuestion
    """
    payload = build_payload(parsed, analysis_data)

    question = QuizQuestion(
        node_id=node_id,
        difficulty=parsed["difficulty"],
        qtype=parsed["qtype"],
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(question)
    db.flush()
    return question


async def import_single(
    raw_text: str,
    db: Session,
    *,
    node_id: int | None = None,
    generate_analysis_flag: bool = True,
) -> dict[str, Any]:
    """单题完整导入流程。

    流程：解析 → 标注（关联知识点）→ 生成解析 → 保存

    Args:
        raw_text: 原始题目文本
        db: 数据库会话
        node_id: 手动指定关联的知识点节点 ID（None 则自动匹配）
        generate_analysis_flag: 是否生成 AI 解析

    Returns:
        {
            "success": bool,
            "question_id": int | None,
            "parsed": dict,
            "node_id": int | None,
            "error": str | None,
        }
    """
    try:
        # 1. AI 解析
        parsed = await parse_question(raw_text, db=db)
        if not parsed["question"]:
            return {"success": False, "question_id": None, "parsed": {}, "node_id": None, "error": "题干解析为空"}

        # 2. 关联知识点
        matched_node_id = node_id
        if matched_node_id is None:
            node = find_matching_node(parsed.get("knowledge_hint", ""), db)
            if node:
                matched_node_id = node.id
                logger.info("自动匹配知识点: %s -> %s (id=%d)", parsed.get("knowledge_hint", ""), node.name, node.id)
            else:
                logger.info("未匹配到知识点: %s", parsed.get("knowledge_hint", ""))

        # 3. 生成解析
        analysis_data = {"analysis": [], "thought_map": "", "error_tips": ""}
        if generate_analysis_flag:
            try:
                analysis_data = await generate_analysis(
                    question=parsed["question"],
                    qtype=parsed["qtype"],
                    options=parsed["options"],
                    correct_answer=parsed["correct_answer"],
                    db=db,
                )
            except Exception as e:
                logger.warning("AI 解析生成失败（不影响保存）: %s", e)

        # 4. 保存
        question = save_question(parsed, analysis_data, matched_node_id, db)
        db.commit()

        return {
            "success": True,
            "question_id": question.id,
            "parsed": parsed,
            "node_id": matched_node_id,
            "error": None,
        }

    except AiGatewayError as e:
        db.rollback()
        logger.error("AI 网关错误: %s", e)
        return {"success": False, "question_id": None, "parsed": {}, "node_id": None, "error": f"AI 调用失败: {e}"}
    except Exception as e:
        db.rollback()
        logger.exception("导入失败")
        return {"success": False, "question_id": None, "parsed": {}, "node_id": None, "error": str(e)}


async def import_batch(
    raw_texts: list[str],
    db: Session,
    *,
    node_id: int | None = None,
    generate_analysis_flag: bool = True,
) -> dict[str, Any]:
    """批量导入题目。

    每题独立处理，单题失败不影响其他。

    Args:
        raw_texts: 原始题目文本列表
        db: 数据库会话
        node_id: 手动指定关联的知识点节点 ID
        generate_analysis_flag: 是否生成 AI 解析

    Returns:
        {
            "total": int,
            "success": int,
            "failed": int,
            "results": list[dict],  # 每题的结果
        }
    """
    results = []
    success_count = 0

    for i, raw_text in enumerate(raw_texts):
        logger.info("批量导入进度: %d/%d", i + 1, len(raw_texts))
        result = await import_single(
            raw_text,
            db,
            node_id=node_id,
            generate_analysis_flag=generate_analysis_flag,
        )
        results.append(result)
        if result["success"]:
            success_count += 1

    return {
        "total": len(raw_texts),
        "success": success_count,
        "failed": len(raw_texts) - success_count,
        "results": results,
    }


def split_questions(raw_text: str) -> list[str]:
    """把包含多道题的文本拆分为单题列表。

    简单规则：按题号（1. 2. 3. 或 1） 2） 等）分割。
    后续可升级为 AI 智能分割。

    Args:
        raw_text: 包含多道题的原始文本

    Returns:
        单题文本列表
    """
    # 匹配题号模式：行首的数字 + . 或 ）
    # 例如 "1. "、"2）"、"10. "、"123. "
    pattern = r'(?:^|\n)\s*(\d+)[\.．、)]\s+'

    parts = re.split(pattern, raw_text)
    # parts 格式: [前文, 题号1, 题目1, 题号2, 题目2, ...]
    # 提取题目部分（奇数索引）
    questions = []
    for i in range(1, len(parts), 2):
        q_text = parts[i + 1] if i + 1 < len(parts) else ""
        q_text = q_text.strip()
        if q_text and len(q_text) > 5:
            questions.append(q_text)

    # 如果没有匹配到题号，认为是单题
    if not questions:
        single = raw_text.strip()
        if single:
            questions = [single]

    return questions
