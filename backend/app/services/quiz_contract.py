"""统一题目契约 v2.0。

职责：
- normalize_payload: 旧格式/不完整格式 → v2.0 标准结构
- validate_payload: 验证 v2.0 结构合法性
- sanitize_for_client: 出题时脱敏（去掉 correct_answer/explanation/analysis）

契约设计原则（借鉴 OpenMAIC DSL 思想）：
- 题目静态数据（题干/选项/标准答案/解析）生成后不变，重做时复用
- 运行时数据（用户作答/错误分析）每次作答独立
- schema_version 标记版本，支持未来迁移
"""
import json
import logging
from typing import Any

logger = logging.getLogger("ailearn.quiz_contract")

SCHEMA_VERSION = "2.0"

# 题型枚举
QTYPE_SINGLE_CHOICE = "single_choice"
QTYPE_MULTIPLE_CHOICE = "multiple_choice"
QTYPE_JUDGE = "judge"
QTYPE_FILL_CLOZE = "fill_cloze"      # 多空填空（题干用 {{n}} 占位符）
QTYPE_FILL_SINGLE = "fill_single"    # 单空填空（兼容旧数据）
QTYPE_SHORT = "short"
QTYPE_CODE = "code"
QTYPE_RECITE = "recite"               # 背诵题（四步渐进记忆阶梯 + 自评）

ALL_QTYPES = (
    QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE,
    QTYPE_FILL_CLOZE, QTYPE_FILL_SINGLE, QTYPE_SHORT, QTYPE_CODE,
    QTYPE_RECITE,
)

# 客观题（规则判卷）
OBJECTIVE_TYPES = (QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE, QTYPE_FILL_CLOZE, QTYPE_FILL_SINGLE)
# 主观题（AI 评分）
SUBJECTIVE_TYPES = (QTYPE_SHORT, QTYPE_CODE)
# 自评题（用户自我评估，不调 AI 判卷）
SELF_RATED_TYPES = (QTYPE_RECITE,)

# 背诵题自评等级 → 分数映射
RECITE_RATING_SCORE = {
    "again": 0,    # 完全不会
    "hard": 40,    # 有点模糊
    "good": 80,    # 记住了
    "easy": 100,   # 太简单
}
RECITE_VALID_RATINGS = tuple(RECITE_RATING_SCORE.keys())

# 旧 qtype → 新 type 的映射
_LEGACY_TYPE_MAP = {
    "choice": QTYPE_SINGLE_CHOICE,
    "fill": QTYPE_FILL_SINGLE,
    "short": QTYPE_SHORT,
    "code": QTYPE_CODE,
}


def normalize_payload(raw: dict[str, Any] | str | None) -> dict[str, Any]:
    """把任意格式的题目 payload 规范化为 v2.0 标准结构。

    兼容：
    - v1.0 旧格式（qtype/question/options/answer/explain）
    - 不完整的 v2.0（缺字段补默认值）
    - JSON 字符串输入
    """
    if raw is None:
        return _empty_payload()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("normalize_payload: raw is invalid JSON, using empty")
            return _empty_payload()
    if not isinstance(raw, dict):
        return _empty_payload()

    # 已经是 v2.0
    if raw.get("schema_version") == SCHEMA_VERSION:
        return _fill_defaults(raw)

    # 旧格式升级
    return _upgrade_from_v1(raw)


def _empty_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": QTYPE_SINGLE_CHOICE,
        "question": "",
        "options": None,
        "blanks": None,
        "content": None,          # recite: 背诵全文
        "segments": None,         # recite: 分段 + 关键词
        "ladder_steps": 4,        # recite: 阶梯步数
        "correct_answer": None,
        "explanation": "",
        "analysis": None,
        "points": 1,
    }


def _fill_defaults(p: dict[str, Any]) -> dict[str, Any]:
    """给 v2.0 结构补缺失的默认字段。"""
    base = _empty_payload()
    base.update(p)
    # 确保 type 合法
    if base["type"] not in ALL_QTYPES:
        base["type"] = _LEGACY_TYPE_MAP.get(base["type"], QTYPE_SINGLE_CHOICE)
    # 选择题确保 options 是列表
    if base["type"] in (QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE):
        if base["options"] is None:
            base["options"] = []
        if base["type"] == QTYPE_JUDGE and not base["options"]:
            base["options"] = ["正确", "错误"]
    # 多空填空确保 blanks 是列表
    if base["type"] == QTYPE_FILL_CLOZE and base["blanks"] is None:
        base["blanks"] = []
    # 背诵题确保 segments 是列表、ladder_steps 有默认值
    if base["type"] == QTYPE_RECITE:
        if base["segments"] is None:
            base["segments"] = []
        if not isinstance(base.get("ladder_steps"), int) or base["ladder_steps"] < 2:
            base["ladder_steps"] = 4
    return base


def _upgrade_from_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """把 v1.0 旧格式升级为 v2.0。"""
    legacy_qtype = raw.get("qtype") or raw.get("question_type") or "choice"
    new_type = _LEGACY_TYPE_MAP.get(legacy_qtype, QTYPE_SINGLE_CHOICE)

    result = _empty_payload()
    result["type"] = new_type
    result["question"] = raw.get("question", "")
    result["explanation"] = raw.get("explain", "") or raw.get("explanation", "")
    result["analysis"] = raw.get("analysis")
    result["points"] = raw.get("points", 1)

    if new_type in (QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE):
        result["options"] = raw.get("options", [])
        # 旧格式 answer 是字母（"A"/"B"），转索引
        ans = raw.get("answer", "")
        if isinstance(ans, str) and len(ans) == 1 and ans.isalpha():
            result["correct_answer"] = ord(ans.upper()) - ord("A")
        else:
            result["correct_answer"] = ans

    elif new_type == QTYPE_FILL_SINGLE:
        result["correct_answer"] = raw.get("answer", "")
        result["blanks"] = [{"id": 1, "answer": raw.get("answer", ""), "hint": None}]

    elif new_type == QTYPE_SHORT:
        result["correct_answer"] = raw.get("answer", "")

    elif new_type == QTYPE_CODE:
        result["correct_answer"] = raw.get("answer", "")
        result["test_cases"] = raw.get("test_cases", [])
        result["language"] = raw.get("language", "python")

    return result


def validate_payload(p: dict[str, Any]) -> list[str]:
    """验证 v2.0 payload 合法性，返回错误列表（空列表=合法）。"""
    errors = []
    if p.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 应为 {SCHEMA_VERSION}，实际 {p.get('schema_version')}")
    if p.get("type") not in ALL_QTYPES:
        errors.append(f"未知题型: {p.get('type')}")
    if not p.get("question"):
        errors.append("question 不能为空")

    qtype = p.get("type")
    if qtype in (QTYPE_SINGLE_CHOICE, QTYPE_MULTIPLE_CHOICE, QTYPE_JUDGE):
        opts = p.get("options")
        if not isinstance(opts, list) or len(opts) < 2:
            errors.append("选择题 options 至少 2 个")
        ca = p.get("correct_answer")
        if qtype == QTYPE_SINGLE_CHOICE and not isinstance(ca, int):
            errors.append("单选 correct_answer 应为选项索引(int)")
        if qtype == QTYPE_MULTIPLE_CHOICE and not isinstance(ca, list):
            errors.append("多选 correct_answer 应为索引列表")

    if qtype == QTYPE_FILL_CLOZE:
        blanks = p.get("blanks")
        if not isinstance(blanks, list) or len(blanks) == 0:
            errors.append("多空填空 blanks 不能为空")
        else:
            for i, b in enumerate(blanks):
                if not isinstance(b, dict) or "id" not in b or "answer" not in b:
                    errors.append(f"blanks[{i}] 缺少 id 或 answer")

    if qtype == QTYPE_RECITE:
        content = p.get("content")
        if not content or not str(content).strip():
            errors.append("背诵题 content（背诵全文）不能为空")
        segments = p.get("segments")
        if segments is not None and not isinstance(segments, list):
            errors.append("背诵题 segments 应为列表")
        elif isinstance(segments, list):
            for i, seg in enumerate(segments):
                if not isinstance(seg, dict):
                    errors.append(f"segments[{i}] 应为对象")
                    continue
                if "text" not in seg or not str(seg.get("text", "")).strip():
                    errors.append(f"segments[{i}] 缺少 text")
                if "keywords" in seg and not isinstance(seg["keywords"], list):
                    errors.append(f"segments[{i}].keywords 应为列表")

    return errors


def sanitize_for_client(p: dict[str, Any]) -> dict[str, Any]:
    """出题时脱敏：去掉答案和解析，只保留渲染所需字段。

    返回给前端的题目数据不应包含 correct_answer / explanation / analysis，
    避免前端作弊。判卷后才返回这些字段。

    背诵题（recite）例外：背诵本身就需要看原文，渐进隐藏是前端交互层面的，
    因此 content / segments / ladder_steps 全部返回，不做脱敏。

    数据结构瘦身：generation_meta（source/template_id/steps/issues 等内部跟踪字段）
    保留在数据库 payload_json 中供调试溯源，但不返回前端。
    """
    safe = {}
    for key in ("type", "question", "options", "points", "difficulty"):
        if key in p:
            safe[key] = p[key]
    # 多空填空只返回 blank id 和 hint，不返回 answer
    if p.get("type") == QTYPE_FILL_CLOZE and p.get("blanks"):
        safe["blanks"] = [
            {"id": b.get("id"), "hint": b.get("hint")}
            for b in p["blanks"]
        ]
    # 背诵题：返回全文和分段（背诵需要看原文，隐藏是前端交互）
    if p.get("type") == QTYPE_RECITE:
        for key in ("content", "segments", "ladder_steps", "explanation"):
            if key in p:
                safe[key] = p[key]
    return safe


def parse_user_answer(raw: Any, qtype: str) -> Any:
    """解析用户答案（前端可能传 JSON 字符串或直接传值）。"""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed
        except (json.JSONDecodeError, TypeError):
            # 简答/代码题就是纯文本
            if qtype in (QTYPE_SHORT, QTYPE_CODE, QTYPE_FILL_SINGLE):
                return raw
            return raw
    return raw
