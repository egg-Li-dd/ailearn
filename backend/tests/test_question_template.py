"""question_template 模块单元测试。

验证：
1. 模板查询与选择
2. 占位符填充
3. 各题型模板实例化生成正确的骨架
4. 生成的骨架兼容 quiz_contract.normalize_payload / validate_payload
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.question_template import (
    BUILTIN_TEMPLATES,
    QuestionTemplate,
    _fill_placeholders,
    _generate_distractors,
    _get_answer_value,
    get_templates,
    instantiate,
    select_template,
)
from app.services.quiz_contract import normalize_payload, validate_payload


# ---------------------------------------------------------------------------
# 测试辅助：构造 mock 知识点节点和参数表
# ---------------------------------------------------------------------------

def _make_node(name="层序遍历", difficulty=3, mastery=60, node_id=1, parent_id=10):
    node = MagicMock()
    node.id = node_id
    node.name = name
    node.difficulty = difficulty
    node.mastery = mastery
    node.parent_id = parent_id
    node.subject_id = 1
    node.summary = ""
    node.notes = ""
    return node


def _make_params():
    return {
        "definition": "二叉树的层序遍历是按层次从上到下、同一层从左到右依次访问每个节点的遍历方式。",
        "core_elements": ["使用队列存储待访问节点", "根节点先入队", "出队时访问并将子节点入队"],
        "key_terms": ["队列", "广度优先搜索", "层次遍历"],
        "formulas": ["时间复杂度 O(n)", "空间复杂度 O(n)"],
        "common_mistakes": ["使用栈而非队列", "忘记判断空树", "子节点入队顺序颠倒"],
        "scope_boundary": "本知识点不涉及前序/中序/后序遍历，不深入平衡二叉树或红黑树。",
        "prerequisites_desc": "需要掌握二叉树基本概念和队列数据结构。",
    }


def _make_sibling(name="前序遍历"):
    sib = MagicMock()
    sib.name = name
    sib.id = 99
    sib.parent_id = 10
    sib.subject_id = 1
    sib.notes = ""
    return sib


# ---------------------------------------------------------------------------
# 模板查询
# ---------------------------------------------------------------------------

class TestGetTemplates:
    def test_all_templates(self):
        templates = get_templates()
        assert len(templates) == len(BUILTIN_TEMPLATES)
        assert all(isinstance(t, QuestionTemplate) for t in templates)

    def test_filter_by_qtype(self):
        sc = get_templates("single_choice")
        assert all(t.qtype == "single_choice" for t in sc)
        assert len(sc) >= 1

        fib = get_templates("fill_cloze")
        assert all(t.qtype == "fill_cloze" for t in fib)

    def test_unknown_qtype_returns_empty(self):
        assert get_templates("nonexistent") == []


# ---------------------------------------------------------------------------
# 模板选择
# ---------------------------------------------------------------------------

class TestSelectTemplate:
    def test_select_single_choice(self):
        node = _make_node()
        params = _make_params()
        siblings = [_make_sibling()]
        t = select_template(node, params, "single_choice", siblings)
        assert t is not None
        assert t.qtype == "single_choice"

    def test_select_judge_wrong_requires_mistakes(self):
        node = _make_node()
        params = _make_params()  # 有 common_mistakes
        siblings = [_make_sibling()]
        t = select_template(node, params, "judge", siblings)
        assert t is not None
        # 有常见错误时，T_JUDGE_WRONG 应该在候选中
        judge_templates = [tmpl for tmpl in get_templates("judge")]
        assert any(tmpl.id == "T_JUDGE_WRONG" for tmpl in judge_templates)

    def test_select_judge_wrong_skipped_without_mistakes(self):
        node = _make_node()
        params = _make_params()
        params["common_mistakes"] = []  # 没有常见错误
        siblings = [_make_sibling()]
        t = select_template(node, params, "judge", siblings)
        assert t is not None
        # 没有常见错误时，不应选 T_JUDGE_WRONG
        assert t.id != "T_JUDGE_WRONG"

    def test_unknown_qtype_returns_none(self):
        node = _make_node()
        params = _make_params()
        assert select_template(node, params, "nonexistent") is None


# ---------------------------------------------------------------------------
# 占位符填充
# ---------------------------------------------------------------------------

class TestFillPlaceholders:
    def test_concept(self):
        node = _make_node(name="测试概念")
        params = _make_params()
        result = _fill_placeholders("{{concept}}的定义", params, node)
        assert result == "测试概念的定义"

    def test_definition(self):
        node = _make_node()
        params = _make_params()
        result = _fill_placeholders("定义：{{definition}}", params, node)
        assert "层序遍历" in result

    def test_element_index(self):
        node = _make_node()
        params = _make_params()
        result = _fill_placeholders("{{element_0}}", params, node)
        assert result == "使用队列存储待访问节点"

    def test_term_index(self):
        node = _make_node()
        params = _make_params()
        result = _fill_placeholders("{{term_0}}", params, node)
        assert result == "队列"

    def test_mixed_placeholders(self):
        node = _make_node(name="哈希表")
        params = _make_params()
        result = _fill_placeholders("{{concept}}的核心是{{element_0}}", params, node)
        assert result == "哈希表的核心是使用队列存储待访问节点"

    def test_out_of_range_index(self):
        node = _make_node()
        params = _make_params()
        result = _fill_placeholders("{{element_99}}", params, node)
        assert result == "要素100"  # 降级返回


# ---------------------------------------------------------------------------
# 答案值解析
# ---------------------------------------------------------------------------

class TestGetAnswerValue:
    def test_definition(self):
        params = _make_params()
        assert _get_answer_value("definition", params) == params["definition"]

    def test_element_0(self):
        params = _make_params()
        assert _get_answer_value("element_0", params) == params["core_elements"][0]

    def test_term_1(self):
        params = _make_params()
        assert _get_answer_value("term_1", params) == params["key_terms"][1]

    def test_true(self):
        assert _get_answer_value("true", {}) == "正确"

    def test_false(self):
        assert _get_answer_value("false", {}) == "错误"


# ---------------------------------------------------------------------------
# 干扰项生成
# ---------------------------------------------------------------------------

class TestGenerateDistractors:
    def test_sibling_definitions(self):
        node = _make_node()
        params = _make_params()
        # 兄弟节点有参数表
        sib = _make_sibling("前序遍历")
        sib.notes = '{"schema_version":"1.0","params":{"definition":"前序遍历是根左右的遍历方式。"}}'
        correct = params["definition"]
        distractors = _generate_distractors("sibling_definitions", node, params, [sib], correct, count=3)
        assert len(distractors) == 3
        assert correct not in distractors

    def test_common_mistakes(self):
        node = _make_node()
        params = _make_params()
        correct = params["core_elements"][0]
        distractors = _generate_distractors("common_mistakes", node, params, [], correct, count=3)
        assert len(distractors) == 3
        assert correct not in distractors

    def test_none_strategy(self):
        node = _make_node()
        params = _make_params()
        distractors = _generate_distractors("none", node, params, [], "answer", count=3)
        # none 策略不生成干扰项，但会用通用干扰项填充
        assert len(distractors) == 3


# ---------------------------------------------------------------------------
# 模板实例化（核心）
# ---------------------------------------------------------------------------

class TestInstantiate:
    def test_single_choice(self):
        node = _make_node()
        params = _make_params()
        siblings = [_make_sibling()]
        template = select_template(node, params, "single_choice", siblings)
        payload = instantiate(template, node, params, siblings)

        assert payload["type"] == "single_choice"
        assert "question" in payload and payload["question"]
        assert "options" in payload and len(payload["options"]) == 4
        assert "correct_answer" in payload
        assert isinstance(payload["correct_answer"], int)
        assert 0 <= payload["correct_answer"] < 4
        assert "explanation" in payload

    def test_multiple_choice(self):
        node = _make_node()
        params = _make_params()
        siblings = [_make_sibling()]
        template = select_template(node, params, "multiple_choice", siblings)
        payload = instantiate(template, node, params, siblings)

        assert payload["type"] == "multiple_choice"
        assert len(payload["options"]) >= 4
        assert isinstance(payload["correct_answer"], list)
        assert len(payload["correct_answer"]) >= 2

    def test_judge_correct(self):
        node = _make_node()
        params = _make_params()
        template = next(t for t in get_templates("judge") if t.id == "T_JUDGE_CORRECT")
        payload = instantiate(template, node, params, [])

        assert payload["type"] == "judge"
        assert payload["options"] == ["正确", "错误"]
        assert payload["correct_answer"] == 0  # 正确

    def test_judge_wrong(self):
        node = _make_node()
        params = _make_params()
        template = next(t for t in get_templates("judge") if t.id == "T_JUDGE_WRONG")
        payload = instantiate(template, node, params, [])

        assert payload["type"] == "judge"
        assert payload["correct_answer"] == 1  # 错误
        assert "常见错误" in payload["question"] or params["common_mistakes"][0] in payload["question"]

    def test_fill_cloze(self):
        node = _make_node()
        params = _make_params()
        template = next(t for t in get_templates("fill_cloze") if t.id == "T_FIB_ELEMENTS")
        payload = instantiate(template, node, params, [])

        assert payload["type"] == "fill_cloze"
        assert "blanks" in payload
        assert len(payload["blanks"]) == 2
        assert all("id" in b and "answer" in b for b in payload["blanks"])
        assert "{{1}}" in payload["question"] or "{{1}}" in payload["question"]

    def test_short_answer(self):
        node = _make_node()
        params = _make_params()
        template = next(t for t in get_templates("short") if t.id == "T_SHORT_EXPLAIN")
        payload = instantiate(template, node, params, [])

        assert payload["type"] == "short"
        assert "correct_answer" in payload
        assert payload["correct_answer"]  # 非空

    def test_difficulty_clamped(self):
        node = _make_node(difficulty=99)
        params = _make_params()
        template = get_templates("single_choice")[0]
        payload = instantiate(template, node, params, [], difficulty=99)
        assert payload["difficulty"] == 5  # 上限

        node2 = _make_node(difficulty=0)
        payload2 = instantiate(template, node2, params, [], difficulty=0)
        assert payload2["difficulty"] == 1  # 下限


# ---------------------------------------------------------------------------
# 与 quiz_contract 的兼容性
# ---------------------------------------------------------------------------

class TestContractCompatibility:
    """模板生成的骨架必须能通过 normalize_payload 和 validate_payload。"""

    @pytest.mark.parametrize("qtype", ["single_choice", "multiple_choice", "judge", "fill_cloze", "short"])
    def test_normalize_and_validate(self, qtype):
        node = _make_node()
        params = _make_params()
        siblings = [_make_sibling()]
        template = select_template(node, params, qtype, siblings)
        if template is None:
            pytest.skip(f"无 {qtype} 模板")
        payload = instantiate(template, node, params, siblings)

        # normalize_payload 不应抛异常
        normalized = normalize_payload(payload)
        assert normalized["schema_version"] == "2.0"
        assert normalized["type"] == qtype

        # validate_payload 不应有严重错误
        errors = validate_payload(normalized)
        # 允许有警告，但不应有结构性错误（如 question 为空、options 不足）
        structural_errors = [e for e in errors if "不能为空" in e or "至少" in e or "应为" in e]
        assert len(structural_errors) == 0, f"结构性错误: {structural_errors}"
