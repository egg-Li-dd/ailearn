"""题目模板库 + 模板实例化（零 AI 调用生成题目骨架）。

设计目标：
- 用知识点参数表（knowledge_refine 生成）填充模板占位符，确定性生成题目骨架
- 不调用 AI，零 token，格式 100% 稳定
- 生成的骨架兼容 quiz_contract.normalize_payload，可直接归一化落库
- AI 仅在需要润色题干表述时可选调用（P1 暂不实现润色，骨架直接可用）

模板占位符约定：
- {{concept}} → 知识点名称
- {{definition}} → 核心定义
- {{element_n}} → 第 n 个核心要素（n 从 0 开始）
- {{term_n}} → 第 n 个关键术语
- {{formula_n}} → 第 n 个公式
- {{mistake_n}} → 第 n 个常见错误
- {{scope}} → 范围边界

干扰项策略：
- sibling_definitions: 从兄弟节点的 definition 取（单选定义题）
- sibling_elements: 从兄弟节点的 core_elements 取（多选/单选要素题）
- common_mistakes: 从本节点的 common_mistakes 取（判断/单选辨析题）
- inverted_elements: 核心要素的否定/颠倒表述（判断题）
"""
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any

from ..models import KnowledgeNode
from .knowledge_refine import get_refined_params

logger = logging.getLogger("ailearn.question_template")


# ---------------------------------------------------------------------------
# 模板数据结构
# ---------------------------------------------------------------------------

@dataclass
class QuestionTemplate:
    """题目模板定义。"""
    id: str
    qtype: str  # 对应 quiz_contract 的题型常量
    name: str
    stem_template: str  # 题干模板，含 {{占位符}}
    answer_source: str  # 正确答案来源字段，如 "definition" / "element_0" / "term_0"
    distractor_strategy: str  # 干扰项策略
    explanation_template: str = "{{definition}}"  # 解析模板
    analysis_template: str = ""  # 易错点模板
    points: int = 1
    # 适用的知识点标签（可选，用于模板匹配）
    requires_formulas: bool = False  # 是否需要公式字段
    requires_mistakes: bool = False  # 是否需要常见错误字段


# ---------------------------------------------------------------------------
# 内置模板库
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES: list[QuestionTemplate] = [
    # ---------- 单选题 ----------
    QuestionTemplate(
        id="T_SC_DEFINITION",
        qtype="single_choice",
        name="概念定义单选",
        stem_template="{{concept}}的定义是？",
        answer_source="definition",
        distractor_strategy="sibling_definitions",
        explanation_template="正确答案：{{definition}}。{{scope}}",
        points=1,
    ),
    QuestionTemplate(
        id="T_SC_WHICH_CORRECT",
        qtype="single_choice",
        name="以下说法正确的是",
        stem_template="以下关于{{concept}}的说法，正确的是？",
        answer_source="element_0",
        distractor_strategy="common_mistakes",
        explanation_template="{{concept}}的核心要素包括：{{element_0}}等。",
        points=1,
    ),
    QuestionTemplate(
        id="T_SC_KEY_TERM",
        qtype="single_choice",
        name="关键术语识别",
        stem_template="在{{concept}}中，核心术语是？",
        answer_source="term_0",
        distractor_strategy="sibling_terms",
        explanation_template="{{concept}}的关键术语是{{term_0}}。",
        points=1,
    ),
    QuestionTemplate(
        id="T_SC_WHICH_WRONG",
        qtype="single_choice",
        name="以下说法错误的是",
        stem_template="以下关于{{concept}}的说法，错误的是？",
        answer_source="mistake_0",
        distractor_strategy="correct_elements",
        explanation_template="错误说法是：{{mistake_0}}。正确的是：{{element_0}}",
        analysis_template="易错点：{{mistake_0}}",
        points=1,
        requires_mistakes=True,
    ),
    # ---------- 多选题 ----------
    QuestionTemplate(
        id="T_MC_ELEMENTS",
        qtype="multiple_choice",
        name="核心要素多选",
        stem_template="以下哪些属于{{concept}}的核心要素？",
        answer_source="core_elements",
        distractor_strategy="sibling_elements",
        explanation_template="{{concept}}的核心要素包括：{{element_0}}等。",
        points=2,
    ),
    # ---------- 判断题 ----------
    QuestionTemplate(
        id="T_JUDGE_CORRECT",
        qtype="judge",
        name="概念陈述判断（正确）",
        stem_template="判断：{{definition}}",
        answer_source="true",
        distractor_strategy="none",
        explanation_template="该陈述正确。{{concept}}的定义是：{{definition}}",
        points=1,
    ),
    QuestionTemplate(
        id="T_JUDGE_WRONG",
        qtype="judge",
        name="概念陈述判断（错误）",
        stem_template="判断：{{mistake_0}}",
        answer_source="false",
        distractor_strategy="none",
        explanation_template="该陈述错误。正确定义是：{{definition}}。常见误区：{{mistake_0}}",
        analysis_template="易错点：{{mistake_0}}",
        points=1,
        requires_mistakes=True,
    ),
    QuestionTemplate(
        id="T_JUDGE_SCOPE",
        qtype="judge",
        name="范围边界判断（错误）",
        stem_template="判断：{{concept}}适用于所有场景，没有任何限制",
        answer_source="false",
        distractor_strategy="none",
        explanation_template="该陈述错误。{{concept}}的适用范围是：{{scope}}",
        analysis_template="易错点：忽略适用范围和边界条件",
        points=1,
    ),
    # ---------- 填空题（多空） ----------
    QuestionTemplate(
        id="T_FIB_DEFINITION",
        qtype="fill_cloze",
        name="核心定义填空（单空）",
        stem_template="{{concept}}是指{{{{1}}}}。",
        answer_source="definition",
        distractor_strategy="none",
        explanation_template="{{concept}}的定义是：{{definition}}",
        points=1,
    ),
    QuestionTemplate(
        id="T_FIB_ELEMENTS",
        qtype="fill_cloze",
        name="核心要素填空（双空）",
        stem_template="{{concept}}的核心要素包括{{{{1}}}}和{{{{2}}}}。",
        answer_source="element_0,element_1",
        distractor_strategy="none",
        explanation_template="{{concept}}的核心要素是{{element_0}}和{{element_1}}。",
        points=2,
    ),
    QuestionTemplate(
        id="T_FIB_TERM",
        qtype="fill_cloze",
        name="关键术语填空（双空）",
        stem_template="在{{concept}}中，核心术语是{{{{1}}}}，其本质是{{{{2}}}}。",
        answer_source="term_0,element_0",
        distractor_strategy="none",
        explanation_template="{{concept}}的核心术语是{{term_0}}，本质是{{element_0}}。",
        points=2,
    ),
    # ---------- 简答题 ----------
    QuestionTemplate(
        id="T_SHORT_EXPLAIN",
        qtype="short",
        name="简述核心原理",
        stem_template="简述{{concept}}的核心原理。",
        answer_source="core_elements",
        distractor_strategy="none",
        explanation_template="评分要点：{{element_0}}；{{element_1}}；{{element_2}}",
        points=3,
    ),
    QuestionTemplate(
        id="T_SHORT_DEFINITION",
        qtype="short",
        name="解释概念定义",
        stem_template="请解释{{concept}}的定义及其核心要素。",
        answer_source="definition+core_elements",
        distractor_strategy="none",
        explanation_template="定义：{{definition}}。核心要素：{{element_0}}、{{element_1}}。",
        points=3,
    ),
]


# ---------------------------------------------------------------------------
# 模板查询与选择
# ---------------------------------------------------------------------------

def get_templates(qtype: str | None = None) -> list[QuestionTemplate]:
    """获取模板列表，可按题型过滤。"""
    if qtype is None:
        return list(BUILTIN_TEMPLATES)
    return [t for t in BUILTIN_TEMPLATES if t.qtype == qtype]


def select_template(
    node: KnowledgeNode,
    params: dict[str, Any],
    qtype: str,
    siblings: list[KnowledgeNode] | None = None,
) -> QuestionTemplate | None:
    """为知识点和题型选择最合适的模板。

    选择逻辑：
    1. 按题型筛选候选模板
    2. 过滤掉前置条件不满足的模板（如需要公式但没有公式、需要常见错误但没有）
    3. 优先选择干扰项策略能满足的模板（如有兄弟节点时优先 sibling 策略）
    4. 随机选择（增加题目多样性）
    """
    candidates = get_templates(qtype)
    if not candidates:
        return None

    # 过滤前置条件
    has_formulas = bool(params.get("formulas"))
    has_mistakes = bool(params.get("common_mistakes"))
    has_siblings = bool(siblings)

    eligible = []
    for t in candidates:
        if t.requires_formulas and not has_formulas:
            continue
        if t.requires_mistakes and not has_mistakes:
            continue
        # 干扰项策略需要兄弟节点但没有兄弟 → 跳过
        if t.distractor_strategy.startswith("sibling") and not has_siblings:
            continue
        # 干扰项策略需要常见错误但没有 → 跳过
        if t.distractor_strategy == "common_mistakes" and not has_mistakes:
            continue
        eligible.append(t)

    if not eligible:
        # 降级：返回该题型的第一个模板（即使干扰项不完美）
        return candidates[0]

    # 优先选择干扰项策略能满足的，然后随机
    return random.choice(eligible)


# ---------------------------------------------------------------------------
# 占位符填充
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z]+)(?:_(\d+))?\}\}")


def _clean_concept(name: str) -> str:
    """去掉知识点编号前缀（如 "1.1 什么是数据结构" → "什么是数据结构"）。"""
    return re.sub(r'^\d+(\.\d+)*\s+', '', name)


def _fill_placeholders(template_str: str, params: dict[str, Any], node: KnowledgeNode) -> str:
    """填充模板中的 {{占位符}}。"""
    def replace(match: re.Match) -> str:
        key = match.group(1)
        index = match.group(2)

        if key == "concept":
            # 去掉知识点编号前缀（如 "1.1 什么是数据结构" → "什么是数据结构"）
            name = node.name
            name = re.sub(r'^\d+(\.\d+)*\s+', '', name)
            return name
        if key == "definition":
            return str(params.get("definition", ""))
        if key == "scope":
            return str(params.get("scope_boundary", ""))
        if key == "element":
            elements = params.get("core_elements", [])
            idx = int(index) if index else 0
            return elements[idx] if idx < len(elements) else f"要素{idx+1}"
        if key == "term":
            terms = params.get("key_terms", [])
            idx = int(index) if index else 0
            return terms[idx] if idx < len(terms) else f"术语{idx+1}"
        if key == "formula":
            formulas = params.get("formulas", [])
            idx = int(index) if index else 0
            return formulas[idx] if idx < len(formulas) else f"公式{idx+1}"
        if key == "mistake":
            mistakes = params.get("common_mistakes", [])
            idx = int(index) if index else 0
            return mistakes[idx] if idx < len(mistakes) else f"误区{idx+1}"
        return match.group(0)

    return _PLACEHOLDER_RE.sub(replace, template_str)


# ---------------------------------------------------------------------------
# 干扰项生成
# ---------------------------------------------------------------------------

def _generate_distractors(
    strategy: str,
    node: KnowledgeNode,
    params: dict[str, Any],
    siblings: list[KnowledgeNode],
    correct_answer: str,
    count: int = 3,
) -> list[str]:
    """根据策略生成干扰项。"""
    distractors: list[str] = []

    if strategy == "sibling_definitions":
        for sib in siblings:
            sib_params = get_refined_params(sib)
            if sib_params:
                d = sib_params.get("definition", "")
                if d and d != correct_answer:
                    distractors.append(d)
            else:
                # 兄弟节点未细化，用名称构造
                d = f"{sib.name}的相关概念"
                if d != correct_answer:
                    distractors.append(d)

    elif strategy == "sibling_elements":
        for sib in siblings:
            sib_params = get_refined_params(sib)
            if sib_params:
                for elem in sib_params.get("core_elements", []):
                    if elem and elem != correct_answer and elem not in distractors:
                        distractors.append(elem)

    elif strategy == "sibling_terms":
        for sib in siblings:
            sib_params = get_refined_params(sib)
            if sib_params:
                for term in sib_params.get("key_terms", []):
                    if term and term != correct_answer and term not in distractors:
                        distractors.append(term)

    elif strategy == "common_mistakes":
        for mistake in params.get("common_mistakes", []):
            if mistake and mistake != correct_answer:
                distractors.append(mistake)

    elif strategy == "correct_elements":
        # 用正确的核心要素作为干扰项（用于"以下说法错误的是"题型）
        for elem in params.get("core_elements", []):
            if elem and elem != correct_answer and elem not in distractors:
                distractors.append(elem)
        for term in params.get("key_terms", []):
            if term and term != correct_answer and term not in distractors:
                distractors.append(term)

    elif strategy == "none":
        pass

    # 不足时用更自然的干扰项填充（避免"以上都不对"等低质量选项）
    clean_name = _clean_concept(node.name)
    generic = [
        f"{clean_name}的一种特殊形式",
        f"与{clean_name}相关的衍生概念",
        f"{clean_name}在特定场景下的变体",
    ]
    for g in generic:
        if len(distractors) >= count:
            break
        if g not in distractors and g != correct_answer:
            distractors.append(g)

    return distractors[:count]


# ---------------------------------------------------------------------------
# 模板实例化（核心）
# ---------------------------------------------------------------------------

def instantiate(
    template: QuestionTemplate,
    node: KnowledgeNode,
    params: dict[str, Any],
    siblings: list[KnowledgeNode] | None = None,
    *,
    difficulty: int | None = None,
) -> dict[str, Any]:
    """将模板实例化为题目骨架（兼容 v2.0 payload 格式）。

    Args:
        template: 题目模板
        node: 知识点节点
        params: 知识点参数表（knowledge_refine 生成）
        siblings: 同级兄弟节点（用于干扰项）
        difficulty: 难度覆盖，默认用节点难度

    Returns:
        dict: v2.0 格式的题目 payload 骨架
    """
    if siblings is None:
        siblings = []

    diff = difficulty if difficulty is not None else node.difficulty
    diff = max(1, min(5, diff))

    # 填充题干和解析
    question = _fill_placeholders(template.stem_template, params, node)
    explanation = _fill_placeholders(template.explanation_template, params, node)
    analysis = _fill_placeholders(template.analysis_template, params, node) if template.analysis_template else None

    qtype = template.qtype
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "type": qtype,
        "question": question,
        "explanation": explanation,
        "analysis": analysis,
        "points": template.points,
        "difficulty": diff,
    }

    # 按题型组装
    if qtype == "single_choice":
        correct = _get_answer_value(template.answer_source, params)
        distractors = _generate_distractors(
            template.distractor_strategy, node, params, siblings, correct, count=3
        )
        options = [correct] + distractors
        random.shuffle(options)
        payload["options"] = options
        payload["correct_answer"] = options.index(correct)

    elif qtype == "multiple_choice":
        correct_elements = params.get("core_elements", [])[:3]
        if not correct_elements:
            correct_elements = [params.get("definition", "")]
        distractors = _generate_distractors(
            template.distractor_strategy, node, params, siblings, "", count=2
        )
        options = correct_elements + distractors
        random.shuffle(options)
        payload["options"] = options
        payload["correct_answer"] = [i for i, opt in enumerate(options) if opt in correct_elements]

    elif qtype == "judge":
        payload["options"] = ["正确", "错误"]
        is_correct = template.answer_source == "true"
        payload["correct_answer"] = 0 if is_correct else 1

    elif qtype == "fill_cloze":
        # answer_source 格式 "element_0,element_1"
        sources = [s.strip() for s in template.answer_source.split(",")]
        blanks = []
        correct_answers = []
        valid_sources = []
        for i, src in enumerate(sources, start=1):
            answer = _get_answer_value(src, params)
            # 过滤掉占位符答案（如 "要素2"、"术语2" 等）
            if re.match(r'^(要素|术语|公式|误区|定义)\d+$', answer):
                logger.debug("fill_cloze: 跳过占位符答案 %s (src=%s)", answer, src)
                continue
            hint = _make_hint(src, params)
            blanks.append({"id": len(blanks) + 1, "answer": answer, "hint": hint})
            correct_answers.append(answer)
            valid_sources.append((i, src))

        # 如果所有空都被过滤了，降级为单空定义题
        if not blanks:
            defi = params.get("definition", "")
            if defi:
                blanks = [{"id": 1, "answer": defi, "hint": "填写定义"}]
                correct_answers = [defi]
                question = f"{_clean_concept(node.name)}是指{{{{1}}}}。"
                payload["question"] = question

        # 调整题干：去掉被过滤的空的占位符，重新编号
        if len(valid_sources) < len(sources):
            # 构建新的题干：只保留有效的空
            new_question = question
            for idx, (orig_i, src) in enumerate(valid_sources, start=1):
                if orig_i != idx:
                    # 把 {{{{orig_i}}}} 替换为 {{{{idx}}}}
                    new_question = new_question.replace(f"{{{{{{{orig_i}}}}}}}", f"{{{{{{{idx}}}}}}}")
            # 去掉被过滤的空的占位符（如 {{{{2}}}}）
            for orig_i in range(1, len(sources) + 1):
                if not any(vs[0] == orig_i for vs in valid_sources):
                    # 去掉 "和{{{{N}}}}" 或 "{{{{N}}}}和" 或 ",{{{{N}}}}" 等
                    pattern = rf'[和与、,，]?\s*{{{{{{{orig_i}}}}}}}\s*[和与、,，]?'
                    new_question = re.sub(pattern, '', new_question)
                    # 去掉多余的标点
                    new_question = re.sub(r'[和与、,，]\s*[。.]', '。', new_question)
                    new_question = re.sub(r'\s+', ' ', new_question).strip()
            payload["question"] = new_question

        payload["blanks"] = blanks
        payload["correct_answer"] = correct_answers

    elif qtype == "fill_single":
        answer = _get_answer_value(template.answer_source, params)
        payload["correct_answer"] = answer

    elif qtype == "short":
        if template.answer_source == "core_elements":
            answer = "；".join(params.get("core_elements", [])[:3])
        elif template.answer_source == "definition+core_elements":
            defi = params.get("definition", "")
            elems = "、".join(params.get("core_elements", [])[:3])
            answer = f"{defi}核心要素：{elems}"
        else:
            answer = _get_answer_value(template.answer_source, params)
        payload["correct_answer"] = answer

    elif qtype == "code":
        # 代码题模板暂不支持确定性生成，返回空骨架
        payload["correct_answer"] = ""
        payload["language"] = "python"
        payload["test_cases"] = []

    return payload


def _get_answer_value(source: str, params: dict[str, Any]) -> str:
    """从 answer_source 解析答案值。"""
    if source == "definition":
        return str(params.get("definition", ""))
    if source == "true":
        return "正确"
    if source == "false":
        return "错误"
    # element_0 / term_0 / formula_0 / mistake_0
    match = re.match(r"(\w+)_(\d+)", source)
    if match:
        key, idx_str = match.groups()
        idx = int(idx_str)
        field_map = {
            "element": "core_elements",
            "term": "key_terms",
            "formula": "formulas",
            "mistake": "common_mistakes",
        }
        field = field_map.get(key, key)
        lst = params.get(field, [])
        return lst[idx] if idx < len(lst) else ""
    return str(params.get(source, ""))


def _make_hint(source: str, params: dict[str, Any]) -> str:
    """为填空题生成提示。"""
    if source.startswith("element"):
        return "核心要素"
    if source.startswith("term"):
        return "关键术语"
    if source.startswith("formula"):
        return "公式"
    if source == "definition":
        return "填写定义"
    return "填写答案"
