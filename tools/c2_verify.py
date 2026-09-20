# -*- coding: utf-8 -*-
"""C2/C4/C5 冒烟：activate 绑定 + state 联动 + 打断批守卫。"""
import json
import sqlite3
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"C:\creategame\AI学\backend\data\ailearn.db"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, None


def ok(label, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + label + ((" | " + str(extra)) if extra else ""))


# 1. activate：绑定课堂到今天的会话（找一个 in_class/pre_class/scheduled 的会话）
con = sqlite3.connect(DB)
row = con.execute("select id, course_id from study_sessions order by id desc limit 1").fetchone()
con.close()
if row:
    s, r = api("POST", "/classroom/activate", {"session_id": row[0]})
    ok("activate binds session", s == 200 and r.get("session_id") == row[0], r)
    s, st = api("GET", "/classroom/state")
    ok("state reflects session", st.get("session_id") == row[0] and "course_name" in st, st.get("course_name"))
else:
    ok("session exists for activate", False, "no sessions in db")

# 2. 小测请求（无 key → 出题守卫 error）
req = urllib.request.Request(
    BASE + "/classroom/interact",
    data=json.dumps({"content": "小测一下吧"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    body = r.read().decode()
ok("batch request guarded without key", "error" in body and "AI" in body, body[:160])

# 3. activate 后 state 课程名非空（数据结构课程绑定）
s, st = api("GET", "/classroom/state")
ok("course name present after activate", bool(st.get("course_name")), st.get("course_name"))

print("done")