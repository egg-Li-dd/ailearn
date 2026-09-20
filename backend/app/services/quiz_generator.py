"""智能出题引擎（Phase 2）。

功能：
1. 按知识点/章节/科目批量生成题目
2. 支持指定难度、题型、数量、出题风格
3. AI 答案验证（生成后自检答案正确性）
4. 生成草稿（不直接入库）→ 人工审核 → 批量入库

设计要点：
- 用 Function Calling 保证结构化输出（比 chat_once + JSON 解析更可靠）
- 批量生成时每题独立，单题失败不影响其他
- 答案验证用独立 AI 调用，交叉验证
- 支持考研真题风格（题干表述、选项设计、难度分布）
"""
import json
import logging
import random
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, QuizQuestion
from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_with_tools, extract_tool_arguments
from .quiz_contract import (
    SCHEMA_VERSION,
    ALL_QTYPES,
    QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE,
    QTYPE_FILL_SINGLE, QTYPE_SHORT,
    normalize_payload,
)

logger = logging.getLogger("ailearn.quiz_generator")

# 出题风格
STYLE_KAOYAN = "kaoyan"       # 考研真题风格
STYLE_TEXTBOOK = "textbook"    # 教材课后题风格
STYLE_BASIC = "basic"          # 基础概念题

VALID_STYLES = (STYLE_KAOYAN, STYLE_TEXTBOOK, STYLE_BASIC)


# ============================================================
# Prompt 模板
# ============================================================

_GENERATE_SYSTEM_PROMPT = """你是一个考研数学命题专家，擅长根据知识点出高质量的练习题。

## 出题要求
1. 题目必须严格围绕指定知识点，不超纲
2. 题干表述清晰、严谨，符合考研真题风格
3. 选项设计要有迷惑性，干扰项应是常见错误答案
4. 难度分级：
   - 1：基础概念题，直接套用公式/定义
   - 2：简单应用题，单步计算
   - 3：中等难度，多步计算或需要一定技巧
   - 4：较难，需要综合运用多个知识点
   - 5：难题，需要巧妙方法或深入理解
5. 所有数学公式必须用 LaTeX 格式：
   - 行内公式 $...$
   - 独立公式 $$...$$

## 题型说明
- single_choice：单选题，4个选项，只有1个正确
- multiple_choice：多选题，4个选项，2-4个正确
- judge：判断题，选项固定为["正确", "错误"]
- fill_single：填空题，答案简洁
- short：简答题/计算题，需要写出解答过程

## 输出要求
必须调用 generate_question 函数返回结构化数据，不要输出额外文本。
"""


_VERIFY_SYSTEM_PROMPT = """你是一个数学题审核专家，负责检查题目和答案的正确性。

## 审核内容
1. 题干是否清晰、无歧义
2. 答案是否正确（需要自己独立计算验证）
3. 解析是否正确、完整
4. 选项设计是否合理（干扰项是否真的有迷惑性）
5. 难度评级是否合理

## 输出要求
必须调用 verify_question 函数返回审核结果：
- is_valid：题目是否有效（true/false）
- score：质量评分（1-10）
- issues：发现的问题列表（如果有）
- corrected_answer：如果答案有误，给出正确答案
- suggestion：改进建议
"""


# ============================================================
# Function Definitions
# ============================================================

_GENERATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "generate_question",
        "description": "根据知识点生成一道练习题",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "题干（含LaTeX公式）"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "选项数组（选择题需要，填空/简答为空数组）",
                },
                "correct_answer": {"type": "string", "description": "标准答案（选择题填选项字母如A或AC，判断填正确/错误）"},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5, "description": "难度1-5"},
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
                    "description": "步骤化解析",
                },
                "thought_map": {"type": "string", "description": "解题思路要点"},
                "error_tips": {"type": "string", "description": "易错点提醒"},
            },
            "required": ["question", "options", "correct_answer", "difficulty", "analysis", "thought_map", "error_tips"],
        },
    },
}


_VERIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "verify_question",
        "description": "审核题目和答案的正确性",
        "parameters": {
            "type": "object",
            "properties": {
                "is_valid": {"type": "boolean", "description": "题目是否有效"},
                "score": {"type": "integer", "minimum": 1, "maximum": 10, "description": "质量评分1-10"},
                "issues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "发现的问题列表",
                },
                "corrected_answer": {"type": "string", "description": "修正后的正确答案（如果原答案有误）"},
                "suggestion": {"type": "string", "description": "改进建议"},
            },
            "required": ["is_valid", "score", "issues", "suggestion"],
        },
    },
}


# ============================================================
# 核心函数
# ============================================================

def get_nodes_by_chapter(db: Session, chapter_node_id: int) -> list[KnowledgeNode]:
    """获取章节下所有知识点节点（level=4）。

    Args:
        chapter_node_id: 章节节点 ID（level=2）

    Returns:
        知识点节点列表
    """
    # 先找章节下的小节（level=3）
    sections = db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.parent_id == chapter_node_id,
            KnowledgeNode.level == 3,
        )
    ).scalars().all()

    # 再找小节下的知识点（level=4）
    section_ids = [s.id for s in sections]
    if not section_ids:
        return []

    points = db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.parent_id.in_(section_ids),
            KnowledgeNode.level == 4,
        )
    ).scalars().all()
    return list(points)


def get_nodes_by_subject(db: Session, subject_id: int) -> list[KnowledgeNode]:
    """获取科目下所有知识点节点（level=4）。"""
    points = db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.subject_id == subject_id,
            KnowledgeNode.level == 4,
        )
    ).scalars().all()
    return list(points)


async def generate_one_question(
    node: KnowledgeNode,
    *,
    qtype: str | None = None,
    difficulty: int | None = None,
    style: str = STYLE_KAOYAN,
    db: Session | None = None,
) -> dict[str, Any]:
    """为单个知识点生成一道题（草稿，不入库）。

    Args:
        node: 知识点节点
        qtype: 强制题型，None 则随机选择
        difficulty: 强制难度，None 则随机选择
        style: 出题风格
        db: 数据库会话

    Returns:
        生成的题目草稿数据：
        {
            "node_id": int,
            "node_name": str,
            "qtype": str,
            "difficulty": int,
            "question": str,
            "options": list,
            "correct_answer": str,
            "analysis": list,
            "thought_map": str,
            "error_tips": str,
            "style": str,
            "generated_at": str,
            "verification": dict | None,  # 验证结果（如果执行了验证）
        }
    """
    # 选择题型
    if qtype is None:
        # 考研数学主要是计算题和填空题，选择题较少
        qtype_weights = [
            (QTYPE_SHORT, 0.5),
            (QTYPE_FILL_SINGLE, 0.25),
            (QTYPE_SINGLE_CHOICE, 0.2),
            (QTYPE_MULTIPLE_CHOICE, 0.05),
        ]
        r = random.random()
        cumulative = 0
        for t, w in qtype_weights:
            cumulative += w
            if r <= cumulative:
                qtype = t
                break
        else:
            qtype = QTYPE_SHORT

    if qtype not in ALL_QTYPES:
        qtype = QTYPE_SHORT

    # 选择难度
    if difficulty is None:
        difficulty = random.choices([1, 2, 3, 4, 5], weights=[0.1, 0.25, 0.35, 0.2, 0.1])[0]
    difficulty = max(1, min(5, difficulty))

    # 风格描述
    style_desc = {
        STYLE_KAOYAN: "考研真题风格，题干严谨，计算量适中，注重综合运用",
        STYLE_TEXTBOOK: "教材课后题风格，基础扎实，循序渐进",
        STYLE_BASIC: "基础概念题，直接考察定义和公式的理解",
    }.get(style, STYLE_KAOYAN)

    # 知识点上下文
    node_context = f"知识点：{node.name}"
    if node.summary:
        node_context += f"\n知识点说明：{node.summary}"

    user_prompt = f"""{node_context}

出题风格：{style_desc}
题型：{qtype}
难度：{difficulty}/5

请根据以上知识点出一道题。"""

    messages = [
        {"role": "system", "content": _GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        set_function_type("quiz")
        result = await chat_with_tools(
            messages,
            tools=[_GENERATE_TOOL_DEF],
            tool_choice={"type": "function", "function": {"name": "generate_question"}},
            temperature=0.7,  # 出题需要一定创造性
            db=db,
        )
    except AiGatewayError as e:
        logger.error("AI 出题失败: node=%d error=%s", node.id, e)
        raise

    generated = extract_tool_arguments(result)
    if not generated:
        raise AiGatewayError("AI 出题失败：未返回结构化数据")

    # 构建草稿
    draft = {
        "node_id": node.id,
        "node_name": node.name,
        "qtype": qtype,
        "difficulty": generated.get("difficulty", difficulty),
        "question": generated.get("question", "").strip(),
        "options": generated.get("options") or [],
        "correct_answer": generated.get("correct_answer", "").strip(),
        "analysis": generated.get("analysis", []),
        "thought_map": generated.get("thought_map", ""),
        "error_tips": generated.get("error_tips", ""),
        "style": style,
        "generated_at": datetime.utcnow().isoformat(),
        "verification": None,
    }

    # 判断题默认选项
    if qtype == QTYPE_JUDGE and not draft["options"]:
        draft["options"] = ["正确", "错误"]

    return draft


async def verify_question(draft: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    """AI 验证题目答案的正确性。

    Args:
        draft: 题目草稿
        db: 数据库会话

    Returns:
        验证结果：
        {
            "is_valid": bool,
            "score": int,
            "issues": list,
            "corrected_answer": str,
            "suggestion": str,
        }
    """
    # 组装题目全文
    parts = [f"【题干】{draft['question']}"]
    if draft["options"]:
        opt_str = "\n".join(f"{chr(65+i)}. {opt}" for i, opt in enumerate(draft["options"]))
        parts.append(f"【选项】\n{opt_str}")
    parts.append(f"【原答案】{draft['correct_answer']}")
    if draft["analysis"]:
        analysis_str = "\n".join(f"步骤{a['step']}: {a['text']}" for a in draft["analysis"])
        parts.append(f"【原解析】\n{analysis_str}")
    full_text = "\n\n".join(parts)

    messages = [
        {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
        {"role": "user", "content": f"请审核以下题目：\n\n{full_text}"},
    ]

    try:
        set_function_type("quiz")
        result = await chat_with_tools(
            messages,
            tools=[_VERIFY_TOOL_DEF],
            tool_choice={"type": "function", "function": {"name": "verify_question"}},
            temperature=0.1,  # 验证需要严谨
            db=db,
        )
    except AiGatewayError as e:
        logger.warning("AI 验证失败: %s", e)
        return {
            "is_valid": True,  # 验证失败时默认通过，不阻塞
            "score": 5,
            "issues": [f"验证服务不可用: {e}"],
            "corrected_answer": "",
            "suggestion": "验证失败，建议人工审核",
        }

    verification = extract_tool_arguments(result)
    if not verification:
        return {
            "is_valid": True,
            "score": 5,
            "issues": ["验证结果解析失败"],
            "corrected_answer": "",
            "suggestion": "建议人工审核",
        }

    return {
        "is_valid": verification.get("is_valid", True),
        "score": verification.get("score", 5),
        "issues": verification.get("issues", []),
        "corrected_answer": verification.get("corrected_answer", ""),
        "suggestion": verification.get("suggestion", ""),
    }


async def generate_batch(
    db: Session,
    *,
    node_ids: list[int] | None = None,
    chapter_id: int | None = None,
    subject_id: int | None = None,
    count: int = 10,
    qtype: str | None = None,
    difficulty: int | None = None,
    style: str = STYLE_KAOYAN,
    verify: bool = True,
) -> dict[str, Any]:
    """批量生成题目草稿。

    Args:
        db: 数据库会话
        node_ids: 指定知识点 ID 列表
        chapter_id: 指定章节节点 ID（取该章节下所有知识点）
        subject_id: 指定科目 ID（取该科目下所有知识点）
        count: 生成题目总数
        qtype: 强制题型，None 则随机
        difficulty: 强制难度，None 则随机
        style: 出题风格
        verify: 是否执行 AI 答案验证

    Returns:
        {
            "total": int,
            "success": int,
            "failed": int,
            "questions": list[dict],  # 成功生成的题目草稿
            "failures": list[dict],   # 失败详情
        }
    """
    # 确定知识点列表
    nodes: list[KnowledgeNode] = []
    if node_ids:
        nodes = db.execute(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))
        ).scalars().all()
    elif chapter_id:
        nodes = get_nodes_by_chapter(db, chapter_id)
    elif subject_id:
        nodes = get_nodes_by_subject(db, subject_id)

    if not nodes:
        raise ValueError("未找到有效的知识点，请检查 node_ids/chapter_id/subject_id")

    logger.info("批量出题: %d 个知识点待选，目标 %d 题", len(nodes), count)

    questions = []
    failures = []
    success_count = 0

    # 循环生成，直到达到目标数量或失败过多
    max_attempts = count * 2  # 最多尝试次数
    attempts = 0

    while len(questions) < count and attempts < max_attempts:
        attempts += 1
        # 随机选择一个知识点
        node = random.choice(nodes)

        try:
            draft = await generate_one_question(
                node,
                qtype=qtype,
                difficulty=difficulty,
                style=style,
                db=db,
            )

            # 验证
            if verify:
                verification = await verify_question(draft, db=db)
                draft["verification"] = verification

                # 如果验证不通过且有修正答案，应用修正
                if not verification["is_valid"] and verification["corrected_answer"]:
                    draft["correct_answer"] = verification["corrected_answer"]
                    draft["verification"]["issues"].append("已自动修正答案")

            questions.append(draft)
            success_count += 1
            logger.info("出题成功 %d/%d: node=%d qtype=%s", success_count, count, node.id, draft["qtype"])

        except Exception as e:
            logger.warning("出题失败 (attempt %d): node=%d error=%s", attempts, node.id, e)
            failures.append({
                "attempt": attempts,
                "node_id": node.id,
                "node_name": node.name,
                "error": str(e),
            })

    return {
        "total": count,
        "success": success_count,
        "failed": len(failures),
        "questions": questions,
        "failures": failures,
    }


def save_questions(
    db: Session,
    questions: list[dict[str, Any]],
    *,
    only_valid: bool = True,
    min_score: int = 0,
) -> dict[str, Any]:
    """批量保存题目草稿到数据库。

    Args:
        db: 数据库会话
        questions: 题目草稿列表
        only_valid: 是否只保存验证通过的题目
        min_score: 最低质量评分（0-10）

    Returns:
        {
            "saved": int,
            "skipped": int,
            "question_ids": list[int],
        }
    """
    saved_ids = []
    skipped = 0

    for draft in questions:
        # 过滤
        if only_valid and draft.get("verification") and not draft["verification"].get("is_valid", True):
            skipped += 1
            continue
        if draft.get("verification") and draft["verification"].get("score", 10) < min_score:
            skipped += 1
            continue

        # 构建 payload
        payload = {
            "schema_version": SCHEMA_VERSION,
            "type": draft["qtype"],
            "question": draft["question"],
            "options": draft["options"] if draft["options"] else None,
            "blanks": None,
            "correct_answer": draft["correct_answer"] or None,
            "explanation": "",
            "analysis": draft.get("analysis", []),
            "points": 1,
            # 扩展字段
            "thought_map": draft.get("thought_map", ""),
            "error_tips": draft.get("error_tips", ""),
            "source": "ai_generated",
            "style": draft.get("style", STYLE_KAOYAN),
            "knowledge_hint": draft.get("node_name", ""),
            "exam_freq": 3,
            "tags": [],
            "generated_at": draft.get("generated_at"),
            "generation_meta": {
                "source": "ai_generator",
                "node_id": draft["node_id"],
                "node_name": draft["node_name"],
                "verification": draft.get("verification"),
            },
        }
        payload = normalize_payload(payload)

        q = QuizQuestion(
            node_id=draft["node_id"],
            difficulty=draft["difficulty"],
            qtype=draft["qtype"],
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        db.add(q)
        db.flush()
        saved_ids.append(q.id)

    db.commit()

    return {
        "saved": len(saved_ids),
        "skipped": skipped,
        "question_ids": saved_ids,
    }
