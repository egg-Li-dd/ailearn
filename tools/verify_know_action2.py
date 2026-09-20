# -*- coding: utf-8 -*-
"""知识节点选区 action 冒烟 v2：必然产生改名动作。"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None


s, tree = req("GET", "/knowledge/tree?subject_id=1")
nodes = []
def walk(lst):
    for n in lst:
        nodes.append(n)
        walk(n.get("children", []))
walk(tree or [])

payload = {
    "context_type": "knowledge_node",
    "items": [{"id": n["id"], "name": n["name"], "difficulty": n["difficulty"], "mastery": n["mastery"]} for n in nodes],
    "instruction": "把章节名称统一加上教材标准编号前缀，如【8.1】",
}
s, r = req("POST", "/ai/action", payload)
print("status:", s)
if isinstance(r, dict):
    print("actions:", json.dumps(r.get("actions", []), ensure_ascii=False)[:400])
    for p in r.get("previews", []):
        print("  preview:", json.dumps(p, ensure_ascii=False)[:180])