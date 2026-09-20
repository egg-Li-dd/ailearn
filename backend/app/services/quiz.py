"""出题与判卷服务。

v2.0 变更：
- 题目 payload 统一为 v2.0 契约（见 quiz_contract.py）
- 新增 fill_cloze 多空填空题型（题干用 {{n}} 占位符，AI 决定挖空位置）
- load_payload 自动归一化旧格式
- grade_answer 支持 v2.0 结构化判卷（含逐空结果）

v2.1 变更：
- 新增 recite 背诵题（四步渐进记忆阶梯 + 自评）
- 背诵题自评完成后自动入 FSRS 复习队列

题型映射（掌握度驱动）：
  <50  single_choice（单选）
  50-70 fill_cloze（多空填空）
  70-85 short（简答）
  >=85 code（代码题）
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, QuizAnswer, QuizQuestion, ReviewQueue
from ..models.enums import ReviewStatus
from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_once
from .code_sandbox import grade_code
from .mastery import apply_quiz_result
from . import review_scheduler
from . import experiment_service
from .knowledge_refine import ensure_refined, get_refined_params, is_refined
from .question_template import instantiate as instantiate_template, select_template
from .quiz_contract import (
    ALL_QTYPES, OBJECTIVE_TYPES, SUBJECTIVE_TYPES, SELF_RATED_TYPES,
    QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE,
    QTYPE_FILL_CLOZE, QTYPE_FILL_SINGLE, QTYPE_SHORT, QTYPE_CODE,
    QTYPE_RECITE, RECITE_RATING_SCORE, RECITE_VALID_RATINGS,
    normalize_payload, validate_payload, parse_user_answer,
)

logger = logging.getLogger("ailearn.quiz")

# 兼容旧代码的别名
QUESTION_TYPES = ALL_QTYPES


def pick_type(mastery: int) -> str:
    """按掌握度选题型。"""
    if mastery < 50:
        return QTYPE_SINGLE_CHOICE
    if mastery < 70:
        return QTYPE_FILL_CLOZE
    if mastery < 85:
        return QTYPE_SHORT
    return QTYPE_CODE


async def generate_from_template(
    db: Session,
    node_id: int,
    force_type: str | None = None,
) -> QuizQuestion:
    """模板驱动出题：用知识点参数表填充模板，零 AI 调用生成题目骨架。

    相比 generate_question（AI 自由生成）：
    - 格式 100% 稳定（确定性生成，无 JSON 解析失败）
    - 零 token 消耗（不调用 AI）
    - 范围严格锚定（题目内容完全来自参数表，不超纲）
    - 题目多样性靠模板选择 + 干扰项随机 + 选项打乱保证

    Args:
        node_id: 知识点节点 ID
        force_type: 强制题型，None 则按掌握度自动选

    Returns:
        QuizQuestion: 落库后的题目

    Raises:
        ValueError: 知识点不存在或无可用模板
    """
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")

    qtype = force_type or pick_type(node.mastery)
    if qtype not in ALL_QTYPES:
        qtype = pick_type(node.mastery)

    # 确保参数表已细化（未细化则即时生成）
    params = await ensure_refined(db, node_id)

    # 取兄弟节点（用于干扰项）
    from .knowledge_refine import get_siblings
    siblings = get_siblings(db, node)

    # 选择模板
    template = select_template(node, params, qtype, siblings)
    if template is None:
        raise ValueError(f"题型 {qtype} 无可用模板")

    # 模板实例化（零 AI 调用）
    payload = instantiate_template(template, node, params, siblings, difficulty=node.difficulty)

    # 归一化 + 校验
    payload = normalize_payload(payload)
    errors = validate_payload(payload)
    if errors:
        logger.warning("generate_from_template validation warnings: %s", errors)

    # 记录出题元数据（来源、流程、问题）
    from .knowledge_refine import is_refined as _is_refined
    _refined = _is_refined(node)
    _params_status = "unknown"
    if node.notes:
        try:
            _nd = json.loads(node.notes)
            _params_status = _nd.get("params_status", "unknown")
        except (json.JSONDecodeError, TypeError):
            pass
    payload["generation_meta"] = {
        "source": "template",
        "template_id": template.id,
        "template_name": template.name,
        "node_refined": _refined,
        "params_status": _params_status,
        "steps": [
            {"step": "check_refined", "ok": _refined, "detail": "知识点已细化" if _refined else "知识点未细化，即时生成参数表"},
            {"step": "select_template", "ok": True, "detail": f"选择模板: {template.name}"},
            {"step": "instantiate", "ok": True, "detail": "模板实例化成功（零AI调用）"},
        ],
        "issues": [f"参数表状态: {_params_status}"] if _params_status != "valid" else [],
    }

    # 落库
    q = QuizQuestion(
        node_id=node.id,
        difficulty=int(min(5, max(1, payload.get("difficulty", node.difficulty)))),
        qtype=qtype,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    logger.info(
        "generate_from_template: node=%d qtype=%s template=%s quiz=%d",
        node_id, qtype, template.id, q.id,
    )
    return q


async def generate_question(db: Session, node_id: int, force_type: str | None = None, *, use_template: bool = False) -> QuizQuestion:
    """按知识点生成一题（v2.0 契约 + 落库）。

    Args:
        force_type: 强制指定题型（如批量出题时指定题型分布），None 则按掌握度自动选。
        use_template: AI生成失败时是否允许fallback到模板生成（默认False=纯AI模式）。
    """
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")

    qtype = force_type or pick_type(node.mastery)
    if qtype not in ALL_QTYPES:
        qtype = pick_type(node.mastery)

    _node_refined = is_refined(node)
    _tried_ai = False
    _ai_error = None

    # A/B 实验分桶：对比 v1（完整示例）与 v2（字段定义表）的 prompt 效果
    _exp = experiment_service.get_experiment(db, "quiz_prompt_v2")
    _variant = experiment_service.assign_variant(_exp, f"node_{node.id}") if _exp else None
    _exp_start = time.monotonic()

    # AI优先：先尝试AI自由生成
    if _variant == "control":
        messages = _build_generation_messages_v1(node, qtype)  # 旧版：完整JSON示例
    else:
        messages = _build_generation_messages(node, qtype)      # 优化版：字段定义表
    try:
        _tried_ai = True
        set_function_type("quiz")
        raw = await chat_once(messages, temperature=0.4)
    except AiGatewayError as e:
        _ai_error = str(e)
        logger.warning("AI出题失败，尝试fallback到模板: %s", e)
        raw = None

    # AI成功：解析并归一化
    if raw is not None:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            if _exp and _variant:
                _exp_duration = int((time.monotonic() - _exp_start) * 1000)
                experiment_service.record_event(_exp, _variant, f"node_{node.id}", "quiz", {
                    "format_valid": False,
                    "duration_ms": _exp_duration,
                })
            _ai_error = f"AI出题格式异常（JSON解析失败）: {e}"
            logger.warning("%s", _ai_error)
            data = None

        if data is not None:
            # 补全 schema_version 和 type（AI 可能不输出）
            data["schema_version"] = "2.0"
            data["type"] = qtype
            # 兼容 AI 用 explain 而不是 explanation
            if "explain" in data and "explanation" not in data:
                data["explanation"] = data.pop("explain")

            payload = normalize_payload(data)
            errors = validate_payload(payload)
            if errors:
                logger.warning("generate_question validation warnings: %s", errors)

            # 记录出题元数据（来源、流程、问题）
            _source = "ai"
            _steps = [
                {"step": "check_refined", "ok": _node_refined, "detail": "知识点已细化" if _node_refined else "知识点未细化"},
                {"step": "ai_generate", "ok": True, "detail": "AI自由生成成功"},
            ]
            _issues = []
            if not _node_refined:
                _issues.append("知识点未细化（无合格参数表），直接使用AI生成")
            if errors:
                _issues.append(f"题目格式校验警告: {errors[:2]}")
            payload["generation_meta"] = {
                "source": _source,
                "node_refined": _node_refined,
                "steps": _steps,
                "issues": _issues,
            }

            q = QuizQuestion(
                node_id=node.id,
                difficulty=int(min(5, max(1, payload.get("difficulty", node.difficulty)))),
                qtype=qtype,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            db.add(q)
            db.commit()
            db.refresh(q)
            logger.info("generate_question(AI): node=%d qtype=%s quiz=%d", node_id, qtype, q.id)
            if _exp and _variant:
                _exp_duration = int((time.monotonic() - _exp_start) * 1000)
                experiment_service.record_event(_exp, _variant, f"node_{node.id}", "quiz", {
                    "format_valid": True,
                    "duration_ms": _exp_duration,
                })
            return q

    # AI失败：fallback到模板生成（如果允许且知识点已细化）
    if use_template and _node_refined:
        logger.info("AI出题失败，fallback到模板生成: %s", _ai_error)
        try:
            q = await generate_from_template(db, node_id, force_type=qtype)
            # 更新元数据，标记为AI降级
            payload = json.loads(q.payload_json)
            meta = payload.get("generation_meta", {})
            meta["source"] = "ai_fallback_template"
            meta.setdefault("steps", []).insert(1, {"step": "ai_generate", "ok": False, "detail": f"AI出题失败: {_ai_error}"})
            meta.setdefault("issues", []).append(f"AI出题失败，已降级为模板生成: {_ai_error}")
            payload["generation_meta"] = meta
            q.payload_json = json.dumps(payload, ensure_ascii=False)
            db.commit()
            return q
        except Exception as e:
            logger.error("模板生成也失败: %s", e)
            raise ValueError(f"AI和模板生成均失败。AI错误: {_ai_error}; 模板错误: {e}")

    # AI失败且不允许fallback
    raise ValueError(f"AI出题失败: {_ai_error}")


def _build_generation_messages(node: KnowledgeNode, qtype: str) -> list[dict]:
    """构建出题消息（优化版：system+user 分离，紧凑字段定义，减少token消耗）。

    优化策略：
    - system: 角色定义 + 输出格式约束 + 字段定义表（代替完整JSON示例）
    - user: 仅参数JSON（knowledge/type/difficulty）
    - 去除冗余字段（schema_version/type/points由后端自动补全）
    - 约束输出长度（explanation≤80字）
    """
    diff = _calibrate(node.difficulty)

    # 通用 system 头部
    sys_header = (
        "你是出题引擎。输出严格JSON，不要其他文字或代码块。"
        "输出紧凑JSON（单行，无缩进无换行）。\n\n"
    )

    # 按题型构建字段定义和规则
    if qtype == QTYPE_SINGLE_CHOICE:
        field_def = (
            "字段定义：\n"
            "- question: string 题干\n"
            "- options: string[4] 四个选项\n"
            "- correct_answer: int 正确选项索引(0-3)\n"
            "- explanation: string 解析(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = ""

    elif qtype == QTYPE_MULTIPLE_CHOICE:
        field_def = (
            "字段定义：\n"
            "- question: string 题干\n"
            "- options: string[5] 五个选项\n"
            "- correct_answer: int[] 正确选项索引数组(至少2个)\n"
            "- explanation: string 解析(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = ""

    elif qtype == QTYPE_JUDGE:
        field_def = (
            "字段定义：\n"
            "- question: string 判断陈述\n"
            "- options: string[2] 固定为[\"正确\",\"错误\"]\n"
            "- correct_answer: int 0=正确,1=错误\n"
            "- explanation: string 解析(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = ""

    elif qtype == QTYPE_FILL_CLOZE:
        field_def = (
            "字段定义：\n"
            "- question: string 题干，用 {{1}}{{2}} 标记挖空位\n"
            "- blanks: object[] 每个含 id(int)对应占位符, answer(string)标准答案, hint(string|null)提示\n"
            "- correct_answer: string[] 答案数组，顺序与blanks一致\n"
            "- explanation: string 解析(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = (
            "\n\n挖空规则：AI决定位置，2-3空，每空对应核心知识点，题干不出现答案。"
        )

    elif qtype == QTYPE_FILL_SINGLE:
        field_def = (
            "字段定义：\n"
            "- question: string 题干（含一个空，用____表示）\n"
            "- correct_answer: string 唯一答案\n"
            "- explanation: string 解析(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = ""

    elif qtype == QTYPE_SHORT:
        field_def = (
            "字段定义：\n"
            "- question: string 简答题题干\n"
            "- correct_answer: string 参考答案（要点）\n"
            "- explanation: string 评分要点(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = ""

    elif qtype == QTYPE_CODE:
        field_def = (
            "字段定义：\n"
            "- question: string 题干（描述要实现的功能）\n"
            "- language: string 编程语言(固定python)\n"
            "- correct_answer: string 参考实现（简短）\n"
            "- explanation: string 解析\n"
            "- test_cases: object[] 每个含 input(string), expected(string)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = "\n\n要求：test_cases 至少3个，覆盖正常/边界。"

    elif qtype == QTYPE_RECITE:
        field_def = (
            "字段定义：\n"
            "- question: string 固定为\"背诵：\"+知识点名\n"
            "- content: string 需背诵的完整文本(80-200字，定义/公式/定理/模板)\n"
            "- segments: object[] 每个含 id(int), text(string), keywords(string[])\n"
            "- ladder_steps: int 固定为4\n"
            "- explanation: string 理解辅助/背景知识(≤60字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = (
            "\n\n要求：segments按语义切分2-5段，拼接后等于content；"
            "每段keywords 1-3个核心词。"
        )

    else:
        field_def = (
            "字段定义：\n"
            "- question: string 题干\n"
            "- correct_answer: string 答案\n"
            "- explanation: string 解析(≤80字)\n"
            "- difficulty: int 难度(1-5)"
        )
        rules = ""

    system_content = sys_header + field_def + rules

    # user 消息：仅参数
    user_content = json.dumps({
        "knowledge": node.name,
        "type": qtype,
        "difficulty": diff,
    }, ensure_ascii=False)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _type_label(t: str) -> str:
    return {
        QTYPE_SINGLE_CHOICE: "单项选择",
        QTYPE_MULTIPLE_CHOICE: "多项选择",
        QTYPE_JUDGE: "判断",
        QTYPE_FILL_CLOZE: "多空填空",
        QTYPE_FILL_SINGLE: "填空",
        QTYPE_SHORT: "简答",
        QTYPE_CODE: "代码",
        QTYPE_RECITE: "背诵",
    }.get(t, "未知")


def _is_empty_answer(parsed: Any, qtype: str) -> bool:
    """判断用户答案是否为空（未作答）。"""
    if parsed is None:
        return True
    if isinstance(parsed, str):
        return not parsed.strip()
    if isinstance(parsed, (dict, list)):
        if not parsed:
            return True
        # dict 全空值也算空
        if isinstance(parsed, dict):
            return all(v is None or str(v).strip() == "" for v in parsed.values())
        return all(v is None or str(v).strip() == "" for v in parsed)
    return False


def _standard_answer_of(payload: dict, qtype: str):
    """取标准答案（空答案反馈用）。"""
    ca = payload.get("correct_answer")
    if qtype == QTYPE_FILL_CLOZE:
        blanks = payload.get("blanks", [])
        return [b.get("answer") for b in blanks if isinstance(b, dict)]
    return ca


def _build_generation_messages_v1(node: KnowledgeNode, qtype: str) -> list[dict]:
    """构建出题消息（旧版 v1：单 user + 完整 JSON 示例，用于 A/B 对照组）。

    与 v2（_build_generation_messages）对比：
    - v1: 单 user 消息，角色+参数+完整JSON示例+要求全部混在一起
    - v2: system+user 分离，字段定义表代替完整示例，预计节省 token 30-40%
    """
    diff = _calibrate(node.difficulty)
    type_label = _type_label(qtype)

    if qtype == QTYPE_SINGLE_CHOICE:
        example = '{"question":"...","options":["A","B","C","D"],"correct_answer":0,"explanation":"...","difficulty":3}'
    elif qtype == QTYPE_MULTIPLE_CHOICE:
        example = '{"question":"...","options":["A","B","C","D","E"],"correct_answer":[0,2],"explanation":"...","difficulty":3}'
    elif qtype == QTYPE_JUDGE:
        example = '{"question":"...","options":["正确","错误"],"correct_answer":0,"explanation":"...","difficulty":3}'
    elif qtype == QTYPE_FILL_CLOZE:
        example = '{"question":"...{{1}}...{{2}}...","blanks":[{"id":1,"answer":"...","hint":null},{"id":2,"answer":"...","hint":null}],"correct_answer":["...","..."],"explanation":"...","difficulty":3}'
    elif qtype == QTYPE_FILL_SINGLE:
        example = '{"question":"...____...","correct_answer":"...","explanation":"...","difficulty":3}'
    elif qtype == QTYPE_SHORT:
        example = '{"question":"...","correct_answer":"...","explanation":"...","difficulty":3}'
    elif qtype == QTYPE_CODE:
        example = '{"question":"...","language":"python","correct_answer":"...","explanation":"...","test_cases":[{"input":"...","expected":"..."}],"difficulty":3}'
    elif qtype == QTYPE_RECITE:
        example = '{"question":"背诵：...","content":"...","segments":[{"id":1,"text":"...","keywords":["..."]}],"ladder_steps":4,"explanation":"...","difficulty":3}'
    else:
        example = '{"question":"...","correct_answer":"...","explanation":"...","difficulty":3}'

    prompt = (
        f"你是出题引擎。请为以下知识点出一道{type_label}题。\n"
        f"知识点：{node.name}\n"
        f"难度：{diff}\n\n"
        f"返回严格 JSON（不要其他文字、不要代码块）：\n{example}\n\n"
        f"要求：\n"
        f"- question 为题干\n"
        f"- correct_answer 为标准答案\n"
        f"- explanation 为解析（不超过80字）\n"
        f"- difficulty 为难度（1-5）\n"
        f"- 输出紧凑 JSON（单行，无缩进无换行）"
    )
    return [{"role": "user", "content": prompt}]


def _calibrate(difficulty: int) -> int:
    return max(1, min(5, difficulty + 1 if difficulty <= 3 else difficulty))


def load_payload(q: QuizQuestion) -> dict:
    """读取题目 payload，自动归一化为 v2.0 格式。"""
    try:
        raw = json.loads(q.payload_json)
    except (json.JSONDecodeError, TypeError):
        raw = {}
    return normalize_payload(raw)


# ============================================================================
# 判卷
# ============================================================================

async def grade_answer(
    db: Session,
    question_id: int,
    user_answer: str,
    *,
    session_id: int | None = None,
    attempt: int = 1,
) -> QuizAnswer:
    """判定作答（v2.0 结构化判卷）。

    Args:
        user_answer: 用户答案。多空填空时为 JSON 字符串 {"1":"队列","2":"O(n)"}；
                      单选时为选项索引（字符串或数字）；简答/代码为纯文本。
        session_id: 关联的测验会话（批量模式），单题模式为 None。
        attempt: 第几次作答（重做时递增）。
    """
    q = db.get(QuizQuestion, question_id)
    if not q:
        raise ValueError(f"题目不存在: {question_id}")

    payload = load_payload(q)
    qtype = payload.get("type", QTYPE_SINGLE_CHOICE)
    parsed_answer = parse_user_answer(user_answer, qtype)

    # 空答案统一处理：不调 AI，直接判未作答 0 分
    if _is_empty_answer(parsed_answer, qtype):
        answer = QuizAnswer(
            question_id=q.id,
            session_id=session_id,
            attempt=attempt,
            user_answer=user_answer,
            score=0,
            ai_feedback=json.dumps(
                {
                    "correct": False,
                    "score": 0,
                    "max_points": payload.get("points", 1),
                    "user_answer": user_answer,
                    "standard_answer": _standard_answer_of(payload, qtype),
                    "explanation": payload.get("explanation", ""),
                    "analysis": payload.get("analysis"),
                    "feedback": "未作答",
                    "unanswered": True,
                },
                ensure_ascii=False,
            ),
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        return answer

    # 按题型判卷
    if qtype == QTYPE_RECITE:
        result = _grade_recite(payload, parsed_answer)
    elif qtype in (QTYPE_SINGLE_CHOICE, QTYPE_JUDGE):
        result = _grade_single_choice(payload, parsed_answer)
    elif qtype == QTYPE_MULTIPLE_CHOICE:
        result = _grade_multiple_choice(payload, parsed_answer)
    elif qtype == QTYPE_FILL_CLOZE:
        result = await _grade_fill_cloze(payload, parsed_answer)
    elif qtype == QTYPE_FILL_SINGLE:
        result = _grade_fill_single(payload, parsed_answer)
    elif qtype == QTYPE_CODE:
        result = await _grade_code(payload, parsed_answer, user_answer)
    else:
        result = await _grade_short(payload, parsed_answer)

    # 客观题：规则判卷后，调用AI生成详细打分反馈（得分理由、知识点讲解、错误分析、改进建议）
    if qtype in OBJECTIVE_TYPES:
        try:
            ai_detail = await _ai_grade_feedback(payload, qtype, parsed_answer, result)
            result.update(ai_detail)
        except Exception as e:
            logger.warning("AI打分反馈生成失败（不影响判卷结果）: %s", e)
            result["ai_feedback_text"] = result.get("explanation", "")

    # 落库
    answer = QuizAnswer(
        question_id=q.id,
        session_id=session_id,
        attempt=attempt,
        user_answer=user_answer,
        score=result["score"],
        ai_feedback=json.dumps(result, ensure_ascii=False),
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    # 掌握度联动（仅首次作答影响，重做不重复影响）
    if attempt <= 1:
        apply_quiz_result(
            db,
            q.node_id,
            score=result["score"],
            is_objective=qtype in OBJECTIVE_TYPES,
            reason=f"题目#{q.id}",
        )

    # 背诵题：自评完成后自动入 FSRS 复习队列
    if qtype == QTYPE_RECITE:
        recite_rating = result.get("recite_rating", "good")
        _ensure_recite_review_queue(db, q.node_id, recite_rating)

    # 错题自动入复习队列（首次作答且分数<60，非背诵题）
    if attempt <= 1 and result["score"] < 60 and qtype != QTYPE_RECITE:
        _ensure_review_queue(db, q.node_id, source="wrong")

    return answer


def _grade_recite(payload: dict, user_answer) -> dict:
    """背诵题自评判卷。

    user_answer 为自评等级字符串：again / hard / good / easy
    不调 AI，直接映射分数并生成鼓励性反馈。
    """
    rating = str(user_answer).strip().lower() if user_answer else "again"
    if rating not in RECITE_VALID_RATINGS:
        rating = "again"

    score = RECITE_RATING_SCORE[rating]
    correct = rating in ("good", "easy")
    content = payload.get("content", "")
    points = payload.get("points", 2)

    feedback_map = {
        "easy": "太棒了！已经完全掌握，继续保持。",
        "good": "记得不错，多复习几次就能脱口而出。",
        "hard": "有点模糊没关系，再看几遍重点关键词。",
        "again": "别灰心，回到第一步重新读几遍，熟能生巧。",
    }

    return {
        "correct": correct,
        "score": score,
        "max_points": points,
        "user_answer": rating,
        "standard_answer": content,
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
        "recite_rating": rating,
        "feedback_text": feedback_map[rating],
    }


def _ensure_review_queue(
    db: Session, node_id: int, *, source: str, fsrs_rating: int | None = None
) -> ReviewQueue | None:
    """确保知识点有 open 的复习队列，可选执行 FSRS 首次评分。

    Args:
        source: 队列来源标记（recite / wrong / sediment）
        fsrs_rating: 若提供则执行 FSRS 首次评分并更新下次到期；None 则仅建队列不评分。
    """
    queue = db.scalar(
        select(ReviewQueue)
        .where(
            ReviewQueue.node_id == node_id,
            ReviewQueue.status == ReviewStatus.OPEN,
        )
        .order_by(ReviewQueue.id.desc())
    )

    now = datetime.now()

    if queue is None:
        queue = ReviewQueue(
            node_id=node_id,
            due_at=now,
            status=ReviewStatus.OPEN,
            source=source,
            fsrs_d=5.0,
            fsrs_s=None,
            fsrs_state="learning",
            fsrs_step=0,
            reps=0,
            lapses=0,
        )
        db.add(queue)
        db.flush()

    if fsrs_rating is not None:
        try:
            review_scheduler.apply_rating(queue, fsrs_rating, now)
        except Exception as e:
            logger.warning("复习队列 FSRS 评分失败: %s", e)

    db.commit()
    db.refresh(queue)
    return queue


def _ensure_recite_review_queue(db: Session, node_id: int, recite_rating: str) -> ReviewQueue | None:
    """背诵题自评完成后，确保该知识点有复习队列并执行 FSRS 首次评分。

    recite_rating: again/hard/good/easy → FSRS 0/1/2/3
    """
    rating_map = {"again": 0, "hard": 1, "good": 2, "easy": 3}
    fsrs_rating = rating_map.get(recite_rating, 2)
    return _ensure_review_queue(db, node_id, source="recite", fsrs_rating=fsrs_rating)


def _grade_single_choice(payload: dict, user_answer) -> dict:
    """单选/判断题判卷。"""
    correct_idx = payload.get("correct_answer")
    options = payload.get("options", [])
    points = payload.get("points", 1)

    # 用户答案可能是索引(int)或字母(str)或选项文本
    user_idx = _normalize_choice_answer(user_answer, options)

    correct = user_idx is not None and user_idx == correct_idx
    score = 100 if correct else 0

    return {
        "correct": correct,
        "score": score,
        "max_points": points,
        "user_answer": user_idx,
        "standard_answer": correct_idx,
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
        "option_results": [
            {"index": i, "text": opt, "is_correct": i == correct_idx, "is_user_choice": i == user_idx}
            for i, opt in enumerate(options)
        ],
    }


def _grade_multiple_choice(payload: dict, user_answer) -> dict:
    """多选题判卷（部分给分）。"""
    correct_set = set(payload.get("correct_answer", []))
    options = payload.get("options", [])
    points = payload.get("points", 2)

    if isinstance(user_answer, list):
        user_set = set(int(x) for x in user_answer if str(x).isdigit())
    elif isinstance(user_answer, str):
        # 兼容 "0,2" 或 "AC" 格式
        user_set = _parse_multi_answer_str(user_answer, options)
    else:
        user_set = set()

    if not correct_set:
        return {"correct": False, "score": 0, "max_points": points, "explanation": payload.get("explanation", "")}

    # 部分给分：选对的比例 - 选错的比例，最低 0
    correct_picked = len(user_set & correct_set)
    wrong_picked = len(user_set - correct_set)
    missed = len(correct_set - user_set)
    ratio = max(0, (correct_picked - wrong_picked) / len(correct_set))
    score = int(ratio * 100)
    all_correct = user_set == correct_set

    return {
        "correct": all_correct,
        "score": score,
        "max_points": points,
        "user_answer": sorted(user_set),
        "standard_answer": sorted(correct_set),
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
        "option_results": [
            {"index": i, "text": opt, "is_correct": i in correct_set, "is_user_choice": i in user_set}
            for i, opt in enumerate(options)
        ],
    }


def _grade_fill_single(payload: dict, user_answer) -> dict:
    """单空填空判卷。"""
    standard = str(payload.get("correct_answer", "")).strip()
    user = str(user_answer).strip() if user_answer is not None else ""
    points = payload.get("points", 1)
    correct = _match_answer(user, standard)
    score = 100 if correct else 0

    return {
        "correct": correct,
        "score": score,
        "max_points": points,
        "user_answer": user,
        "standard_answer": standard,
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
    }


async def _grade_fill_cloze(payload: dict, user_answer) -> dict:
    """多空填空判卷（逐空比对 + AI 错误分析）。"""
    blanks = payload.get("blanks", [])
    points = payload.get("points", 2)
    question_text = payload.get("question", "")

    # user_answer 应为 dict {"1": "队列", "2": "O(n)"}
    if not isinstance(user_answer, dict):
        user_answers = {}
    else:
        user_answers = {str(k): str(v) for k, v in user_answer.items()}

    blank_results = []
    correct_count = 0

    for blank in blanks:
        blank_id = str(blank.get("id"))
        standard = str(blank.get("answer", "")).strip()
        user_val = user_answers.get(blank_id, "").strip()
        is_correct = _match_answer(user_val, standard)

        if is_correct:
            correct_count += 1
            error_analysis = None
        else:
            error_analysis = await _generate_blank_error_analysis(
                question_text, blank.get("id"), user_val, standard,
                payload.get("explanation", "")
            )

        blank_results.append({
            "blank_id": blank.get("id"),
            "user_answer": user_val,
            "standard": standard,
            "correct": is_correct,
            "error_analysis": error_analysis,
        })

    total = len(blanks) if blanks else 1
    score = int(correct_count / total * 100)
    all_correct = bool(blanks) and correct_count == len(blanks)

    return {
        "correct": all_correct,
        "score": score,
        "max_points": points,
        "user_answer": user_answers,
        "standard_answer": [b.get("answer") for b in blanks],
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
        "blank_results": blank_results,
    }


async def _grade_code(payload: dict, parsed_answer, raw_user_answer: str) -> dict:
    """代码题判卷（沙箱执行优先，fallback AI 评分）。"""
    points = payload.get("points", 5)
    sandbox_result = grade_code(payload, raw_user_answer)

    if not sandbox_result.get("fallback") and sandbox_result.get("score") is not None:
        score = sandbox_result["score"]
        feedback = sandbox_result["feedback"]
    else:
        prompt = (
            f"题目：{payload.get('question')}\n标准答案：{payload.get('correct_answer','')}\n"
            f"学生代码：\n```\n{raw_user_answer}\n```\n\n"
            f"请评分（0-100 整数）并给一句简短点评。返回严格 JSON："
            f'{{"score":0,"feedback":"..."}}'
        )
        try:
            set_function_type("quiz_answer")
            raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.1)
            judged = json.loads(raw.strip())
            score = max(0, min(100, int(judged.get("score", 0))))
            feedback = judged.get("feedback", "")
        except (json.JSONDecodeError, ValueError, AiGatewayError):
            score = 50
            feedback = payload.get("explanation", "")

    return {
        "correct": score >= 60,
        "score": score,
        "max_points": points,
        "user_answer": raw_user_answer,
        "standard_answer": payload.get("correct_answer", ""),
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
        "ai_feedback_text": feedback,
    }


async def _grade_short(payload: dict, user_answer) -> dict:
    """简答题 AI 评分。"""
    points = payload.get("points", 3)
    standard = payload.get("correct_answer", "")
    user_text = str(user_answer) if user_answer else ""

    prompt = (
        f"题目：{payload.get('question')}\n参考答案：{standard}\n"
        f"学生作答：{user_text}\n\n"
        f"请评分（0-100 整数）并给一句简短点评，指出学生的错误或不足。返回严格 JSON："
        f'{{"score":0,"feedback":"..."}}'
    )
    try:
        raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.1)
        judged = json.loads(raw.strip())
        score = max(0, min(100, int(judged.get("score", 0))))
        feedback = judged.get("feedback", "")
    except (json.JSONDecodeError, ValueError, AiGatewayError):
        score = 50
        feedback = payload.get("explanation", "")

    return {
        "correct": score >= 60,
        "score": score,
        "max_points": points,
        "user_answer": user_text,
        "standard_answer": standard,
        "explanation": payload.get("explanation", ""),
        "analysis": payload.get("analysis"),
        "ai_feedback_text": feedback,
    }


async def _ai_grade_feedback(
    payload: dict,
    qtype: str,
    user_answer,
    rule_result: dict,
) -> dict:
    """客观题AI打分反馈：在规则判卷后，调用AI生成详细评分反馈。

    包含：得分确认、知识点讲解、错误分析、改进建议。
    不改变规则判卷的分数（确保客观性），只增加AI的详细反馈。
    """
    question_text = payload.get("question", "")
    options = payload.get("options", [])
    correct_answer = payload.get("correct_answer")
    explanation = payload.get("explanation", "")
    analysis = payload.get("analysis", "")
    rule_score = rule_result.get("score", 0)
    rule_correct = rule_result.get("correct", False)

    # 构建用户答案的可读形式
    if qtype in (QTYPE_SINGLE_CHOICE, QTYPE_JUDGE):
        user_idx = rule_result.get("user_answer")
        user_answer_text = options[user_idx] if isinstance(user_idx, int) and user_idx < len(options) else str(user_answer)
        correct_text = options[correct_answer] if isinstance(correct_answer, int) and correct_answer < len(options) else str(correct_answer)
    elif qtype == QTYPE_MULTIPLE_CHOICE:
        user_indices = rule_result.get("user_answer", [])
        correct_indices = rule_result.get("standard_answer", [])
        user_answer_text = "、".join(f"{chr(65+i)}.{options[i]}" for i in user_indices if isinstance(i, int) and i < len(options))
        correct_text = "、".join(f"{chr(65+i)}.{options[i]}" for i in correct_indices if isinstance(i, int) and i < len(options))
    else:
        user_answer_text = str(user_answer)
        correct_text = str(correct_answer)

    type_label = {
        QTYPE_SINGLE_CHOICE: "单选题",
        QTYPE_MULTIPLE_CHOICE: "多选题",
        QTYPE_JUDGE: "判断题",
    }.get(qtype, "题目")

    prompt = (
        f"你是一个严格的阅卷老师。请对以下{type_label}进行详细评分反馈。\n\n"
        f"【题目】{question_text}\n"
    )
    if options:
        prompt += "【选项】\n"
        for i, opt in enumerate(options):
            prompt += f"{chr(65+i)}. {opt}\n"
    prompt += (
        f"\n【学生答案】{user_answer_text}\n"
        f"【标准答案】{correct_text}\n"
        f"【规则判卷】得分 {rule_score}/100，{'正确' if rule_correct else '错误'}\n"
    )
    if explanation:
        prompt += f"【题目解析】{explanation}\n"
    if analysis:
        prompt += f"【易错点】{analysis}\n"

    prompt += (
        "\n请给出详细评分反馈，返回严格 JSON（不要任何其他文字、不要代码块）：\n"
        '{"score_confirmed": 0-100整数（确认最终得分，应与规则判卷一致）,'
        '"score_reason": "得分理由（一句话说明为什么得这个分）",'
        '"knowledge_explain": "相关知识点讲解（50字内，讲清本题考察的核心概念）",'
        '"error_analysis": "错误分析（如果答错，说明错在哪里；如果答对，说明答对的关键点）",'
        '"improvement_suggestion": "改进建议（一句话，针对学生的薄弱点给出学习建议）"}'
    )

    try:
        set_function_type("quiz_answer")
        raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.2)
        judged = json.loads(raw.strip())
        score_confirmed = max(0, min(100, int(judged.get("score_confirmed", rule_score))))
        score_reason = judged.get("score_reason", "")
        knowledge_explain = judged.get("knowledge_explain", "")
        error_analysis = judged.get("error_analysis", "")
        improvement_suggestion = judged.get("improvement_suggestion", "")
    except (json.JSONDecodeError, ValueError, AiGatewayError) as e:
        logger.warning("AI打分反馈解析失败，使用默认反馈: %s", e)
        score_confirmed = rule_score
        score_reason = "规则判卷得分"
        knowledge_explain = explanation
        error_analysis = "答对了" if rule_correct else "答错了，请查看解析"
        improvement_suggestion = "继续加油"

    return {
        "score": score_confirmed,  # AI确认的最终得分（应与规则一致）
        "ai_score": score_confirmed,
        "score_reason": score_reason,
        "knowledge_explain": knowledge_explain,
        "error_analysis": error_analysis,
        "improvement_suggestion": improvement_suggestion,
        "ai_feedback_text": f"得分理由：{score_reason}\n知识点讲解：{knowledge_explain}\n错误分析：{error_analysis}\n改进建议：{improvement_suggestion}",
        "ai_graded": True,
    }


# ============================================================================
# 辅助函数
# ============================================================================

def _match_answer(user: str, standard: str) -> bool:
    """填空题答案匹配规则。

    1. 忽略前后空格
    2. 忽略大小写
    3. 支持标准答案包含多个可接受答案（用 | 分隔）
    4. 支持常见同义词表
    """
    user = user.strip().lower()
    standard = standard.strip().lower()

    if not user:
        return False
    if user == standard:
        return True

    # 多可接受答案
    if "|" in standard:
        acceptables = [a.strip() for a in standard.split("|")]
        if user in acceptables:
            return True

    # 同义词表
    SYNONYMS = {
        "队列": {"queue", "先进先出", "fifo"},
        "栈": {"stack", "后进先出", "lifo", "堆栈"},
        "o(n)": {"on", "线性", "o(n)"},
        "o(nlogn)": {"onlogn", "o(n log n)", "o(nlogn)"},
        "o(1)": {"o1", "常数", "o(1)"},
        "o(logn)": {"ologn", "o(log n)", "对数"},
        "o(n^2)": {"on2", "o(n2)", "平方", "o(n^2)"},
        "广度优先搜索": {"bfs", "广度优先", "宽度优先搜索"},
        "深度优先搜索": {"dfs", "深度优先"},
        "二叉搜索树": {"bst", "二叉排序树", "二叉查找树"},
    }
    if user in SYNONYMS.get(standard, set()):
        return True
    for key, syns in SYNONYMS.items():
        if standard in syns and user == key:
            return True
        if standard == key and user in syns:
            return True

    return False


def _normalize_choice_answer(user_answer, options: list) -> int | None:
    """把用户答案归一化为选项索引。

    支持：整数索引、字母(A/B/C/D)、选项文本。
    """
    if user_answer is None:
        return None
    if isinstance(user_answer, int):
        return user_answer if 0 <= user_answer < len(options) else None
    if isinstance(user_answer, float) and user_answer.is_integer():
        idx = int(user_answer)
        return idx if 0 <= idx < len(options) else None

    s = str(user_answer).strip()
    # 纯数字
    if s.isdigit():
        idx = int(s)
        return idx if 0 <= idx < len(options) else None
    # 字母 A/B/C/D
    if len(s) == 1 and s.isalpha():
        idx = ord(s.upper()) - ord("A")
        return idx if 0 <= idx < len(options) else None
    # 选项文本匹配
    for i, opt in enumerate(options):
        if str(opt).strip() == s:
            return i
    return None


def _parse_multi_answer_str(s: str, options: list) -> set:
    """解析多选答案字符串（"0,2" 或 "AC" 或 "A,C"）。"""
    s = s.strip()
    result = set()
    # 逗号分隔
    if "," in s:
        for part in s.split(","):
            idx = _normalize_choice_answer(part.strip(), options)
            if idx is not None:
                result.add(idx)
    # 纯字母连写 "AC"
    elif s.isalpha():
        for ch in s:
            idx = _normalize_choice_answer(ch, options)
            if idx is not None:
                result.add(idx)
    # 空格分隔
    elif " " in s:
        for part in s.split():
            idx = _normalize_choice_answer(part, options)
            if idx is not None:
                result.add(idx)
    return result


async def _generate_blank_error_analysis(
    question: str, blank_id, user_answer: str, standard: str, explanation: str
) -> str:
    """为错误的空生成 AI 错误分析。"""
    if not user_answer:
        return f"此空未作答，正确答案是「{standard}」。"
    prompt = (
        f"题目：{question}\n"
        f"第{blank_id}空，学生填了「{user_answer}」，正确答案是「{standard}」。\n"
        f"题目解析：{explanation}\n\n"
        f"请用一句话指出学生的错误原因，并给出正确思路。"
        f"不要重复题目，不要说套话，直接讲错在哪、为什么错。控制在60字以内。"
    )
    try:
        set_function_type("quiz_answer")
        return await asyncio.wait_for(
            chat_once([{"role": "user", "content": prompt}], temperature=0.2),
            timeout=20.0,
        )
    except (AiGatewayError, asyncio.TimeoutError):
        return f"你填了「{user_answer}」，正确答案是「{standard}」。"


def recent_questions(db: Session, node_id: int, limit: int = 5) -> list[QuizQuestion]:
    return list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.node_id == node_id)
            .order_by(QuizQuestion.id.desc())
            .limit(limit)
        )
    )
