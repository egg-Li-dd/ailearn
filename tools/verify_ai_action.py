# -*- coding: utf-8 -*-
"""AI action 端点冒烟：选区课表行 → 指令 → 动作 JSON。"""
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
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, None


# 取现有课表行做选区
s, sched = req("GET", "/schedule")
print("schedule rows:", s, len(sched) if isinstance(sched, list) else sched)
s, courses = req("GET", "/courses")
course_map = {c["id"]: c["name"] for c in courses}

items = []
for it in (sched or [])[:3]:
    items.append({
        "id": it["id"], "weekday": it["weekday"], "start_time": it["start_time"][:5],
        "end_time": it["end_time"][:5], "location": it["location"],
        "course_id": it["course_id"],
    })

payload = {
    "context_type": "schedule_item",
    "items": items,
    "instruction": "把课程时间整体顺延 30 分钟",
}
s, r = req("POST", "/ai/action", payload)
print("status:", s)
if s == 200:
    print("note:", r.get("note"))
    print("actions:", json.dumps(r.get("actions", []), ensure_ascii=False))
    print("preview size:", len(r.get("previews", [])))
    for p in r.get("previews", []):
        print("  preview:", json.dumps(p, ensure_ascii=False)[:200])