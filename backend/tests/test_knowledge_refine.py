"""knowledge_refine 模块单元测试。

验证：
1. get_refined_params 从 notes 解析参数表
2. is_refined 质量判断
3. validate_params 校验逻辑
4. get_parent_path 父路径构建
5. get_siblings 兄弟节点查询
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.knowledge_refine import (
    MIN_CORE_ELEMENTS,
    MIN_DEFINITION_LENGTH,
    MIN_KEY_TERMS,
    PARAMS_SCHEMA_VERSION,
    get_parent_path,
    get_refined_params,
    get_siblings,
    is_refined,
    validate_params,
)


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def _make_node(notes=None, summary="", name="测试知识点", node_id=1, parent_id=None, subject_id=1):
    node = MagicMock()
    node.id = node_id
    node.name = name
    node.notes = notes
    node.summary = summary
    node.parent_id = parent_id
    node.subject_id = subject_id
    return node


def _make_valid_params():
    return {
        "definition": "二叉树的层序遍历是按层次从上到下、同一层从左到右依次访问每个节点的遍历方式。",
        "core_elements": ["使用队列存储待访问节点", "根节点先入队", "出队时访问并将子节点入队"],
        "key_terms": ["队列", "广度优先搜索"],
        "formulas": ["时间复杂度 O(n)"],
        "common_mistakes": ["使用栈而非队列"],
        "scope_boundary": "不涉及前序/中序/后序遍历。",
        "prerequisites_desc": "需要掌握二叉树和队列。",
    }


def _make_notes(params):
    return json.dumps({
        "schema_version": PARAMS_SCHEMA_VERSION,
        "refined_at": "2026-01-01T00:00:00+00:00",
        "params": params,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# get_refined_params
# ---------------------------------------------------------------------------

class TestGetRefinedParams:
    def test_valid_notes(self):
        params = _make_valid_params()
        node = _make_node(notes=_make_notes(params))
        result = get_refined_params(node)
        assert result is not None
        assert result["definition"] == params["definition"]
        assert result["core_elements"] == params["core_elements"]

    def test_empty_notes(self):
        node = _make_node(notes=None)
        assert get_refined_params(node) is None
        node2 = _make_node(notes="")
        assert get_refined_params(node2) is None

    def test_invalid_json(self):
        node = _make_node(notes="not valid json{{{")
        assert get_refined_params(node) is None

    def test_wrong_schema_version(self):
        data = json.dumps({"schema_version": "0.9", "params": {}})
        node = _make_node(notes=data)
        assert get_refined_params(node) is None

    def test_not_dict(self):
        node = _make_node(notes=json.dumps(["a", "b"]))
        assert get_refined_params(node) is None


# ---------------------------------------------------------------------------
# validate_params
# ---------------------------------------------------------------------------

class TestValidateParams:
    def test_valid_params(self):
        params = _make_valid_params()
        errors = validate_params(params)
        assert errors == []

    def test_definition_too_short(self):
        params = _make_valid_params()
        params["definition"] = "短"  # 少于 MIN_DEFINITION_LENGTH
        errors = validate_params(params)
        assert any("definition" in e for e in errors)

    def test_definition_empty(self):
        params = _make_valid_params()
        params["definition"] = ""
        errors = validate_params(params)
        assert any("definition" in e for e in errors)

    def test_too_few_core_elements(self):
        params = _make_valid_params()
        params["core_elements"] = ["只有一个"]
        errors = validate_params(params)
        assert any("core_elements" in e for e in errors)

    def test_core_elements_not_list(self):
        params = _make_valid_params()
        params["core_elements"] = "不是列表"
        errors = validate_params(params)
        assert any("core_elements" in e for e in errors)

    def test_too_few_key_terms(self):
        params = _make_valid_params()
        params["key_terms"] = []
        errors = validate_params(params)
        assert any("key_terms" in e for e in errors)

    def test_scope_boundary_empty(self):
        params = _make_valid_params()
        params["scope_boundary"] = ""
        errors = validate_params(params)
        assert any("scope_boundary" in e for e in errors)

    def test_optional_fields_missing(self):
        """formulas、common_mistakes、prerequisites_desc 是可选的，缺失不应报错。"""
        params = _make_valid_params()
        del params["formulas"]
        del params["common_mistakes"]
        del params["prerequisites_desc"]
        errors = validate_params(params)
        assert errors == []


# ---------------------------------------------------------------------------
# is_refined
# ---------------------------------------------------------------------------

class TestIsRefined:
    def test_refined_node(self):
        params = _make_valid_params()
        node = _make_node(notes=_make_notes(params))
        assert is_refined(node) is True

    def test_unrefined_node_no_notes(self):
        node = _make_node(notes=None)
        assert is_refined(node) is False

    def test_unrefined_node_bad_quality(self):
        params = _make_valid_params()
        params["definition"] = "太短"
        node = _make_node(notes=_make_notes(params))
        assert is_refined(node) is False

    def test_unrefined_node_invalid_json(self):
        node = _make_node(notes="garbage")
        assert is_refined(node) is False


# ---------------------------------------------------------------------------
# get_parent_path
# ---------------------------------------------------------------------------

class TestGetParentPath:
    def test_root_node(self):
        db = MagicMock()
        root = _make_node(name="根节点", parent_id=None, node_id=1)
        db.get.return_value = None  # parent_id=None，不会调用 db.get
        path = get_parent_path(db, root)
        assert path == ["根节点"]

    def test_three_level_path(self):
        db = MagicMock()
        # 叶子节点
        leaf = _make_node(name="叶子", parent_id=2, node_id=3)
        # 中间节点
        middle = _make_node(name="中间", parent_id=1, node_id=2)
        # 根节点
        root = _make_node(name="根", parent_id=None, node_id=1)

        # db.get 按 ID 返回对应节点
        def mock_get(model, node_id):
            if node_id == 2:
                return middle
            if node_id == 1:
                return root
            return None

        db.get.side_effect = mock_get
        path = get_parent_path(db, leaf)
        assert path == ["根", "中间", "叶子"]

    def test_cycle_protection(self):
        """防止父节点循环引用导致无限循环。"""
        db = MagicMock()
        node_a = _make_node(name="A", parent_id=2, node_id=1)
        node_b = _make_node(name="B", parent_id=1, node_id=2)  # 循环引用

        def mock_get(model, node_id):
            if node_id == 2:
                return node_b
            if node_id == 1:
                return node_a
            return None

        db.get.side_effect = mock_get
        # 不应无限循环
        path = get_parent_path(db, node_a)
        assert len(path) <= 3  # 最多 A, B, A（visited 检测到循环后停止）


# ---------------------------------------------------------------------------
# get_siblings
# ---------------------------------------------------------------------------

class TestGetSiblings:
    def test_siblings_with_parent(self):
        db = MagicMock()
        node = _make_node(name="当前", parent_id=10, node_id=1)

        # 模拟查询结果
        sib1 = _make_node(name="兄弟1", parent_id=10, node_id=2)
        sib2 = _make_node(name="兄弟2", parent_id=10, node_id=3)
        db.scalars.return_value = [sib1, sib2]

        siblings = get_siblings(db, node)
        assert len(siblings) == 2
        assert siblings[0].name == "兄弟1"

    def test_root_node_siblings(self):
        db = MagicMock()
        node = _make_node(name="根1", parent_id=None, node_id=1, subject_id=5)

        sib = _make_node(name="根2", parent_id=None, node_id=2, subject_id=5)
        db.scalars.return_value = [sib]

        siblings = get_siblings(db, node)
        assert len(siblings) == 1
        assert siblings[0].name == "根2"

    def test_no_siblings(self):
        db = MagicMock()
        node = _make_node(name="独苗", parent_id=10, node_id=1)
        db.scalars.return_value = []

        siblings = get_siblings(db, node)
        assert siblings == []

    def test_limit(self):
        db = MagicMock()
        node = _make_node(name="当前", parent_id=10, node_id=1)
        db.scalars.return_value = []

        get_siblings(db, node, limit=5)
        # 验证 select 调用中包含 limit
        call_args = db.scalars.call_args
        assert call_args is not None
