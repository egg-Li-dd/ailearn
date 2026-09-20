# -*- coding: utf-8 -*-
"""知识节点选区 action 冒烟。"""
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
print("nodes:", len(nodes))
if not nodes:
    raise SystemExit("no nodes")

sel = nodes[:3]
payload = {
    "context_type": "knowledge_node",
    "items": [{"id": n["id"], "name": n["name"], "difficulty": n["difficulty"], "mastery": n["mastery"]} for n in sel],
    "instruction": "掌握度低于40的节点难度调整为1",
}
s, r = req("POST", "/ai/action", payload)
print("status:", s)
print("actions:", json.dumps(r.get("actions", []), ensure_ascii=False)[:300] if isinstance(r, dict) else r)
print("previews:", len(r.get("previews", [])) if isinstance(r, dict) else 0)