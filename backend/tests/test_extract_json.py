"""_extract_json 函数单元测试"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.ai_action import _extract_json


class TestExtractJson:
    def test_plain_json(self):
        raw = '{"items":[{"name":"测试"}]}'
        result = _extract_json(raw)
        assert json.loads(result)["items"][0]["name"] == "测试"

    def test_code_block(self):
        raw = '```json\n{"items":[]}\n```'
        result = _extract_json(raw)
        assert json.loads(result)["items"] == []

    def test_surrounding_text(self):
        raw = '好的，这是结果：{"items":[{"a":1}]} 希望对你有帮助'
        result = _extract_json(raw)
        assert json.loads(result)["items"][0]["a"] == 1

    def test_brace_in_string(self):
        raw = '{"items":[{"name":"a}b"}]}'
        result = _extract_json(raw)
        assert json.loads(result)["items"][0]["name"] == "a}b"

    def test_nested_json(self):
        raw = '{"actions":[{"id":1,"fields":{"name":"x"}}]}'
        result = _extract_json(raw)
        assert json.loads(result)["actions"][0]["fields"]["name"] == "x"

    def test_escaped_chars(self):
        raw = '{"items":[{"name":"他说\\"你好\\""}]}'
        result = _extract_json(raw)
        assert json.loads(result)["items"][0]["name"] == '他说"你好"'

    def test_empty_items(self):
        raw = '{"items":[]}'
        result = _extract_json(raw)
        assert json.loads(result)["items"] == []

    def test_actions_empty(self):
        raw = '{"actions":[]}'
        result = _extract_json(raw)
        assert json.loads(result)["actions"] == []

    def test_multiline_json(self):
        raw = '''{
  "items": [
    {"name": "a"},
    {"name": "b"}
  ]
}'''
        result = _extract_json(raw)
        data = json.loads(result)
        assert len(data["items"]) == 2
        assert data["items"][1]["name"] == "b"

    def test_code_block_with_language(self):
        raw = '```json\n{"items":[{"id":1}]}\n```'
        result = _extract_json(raw)
        assert json.loads(result)["items"][0]["id"] == 1
