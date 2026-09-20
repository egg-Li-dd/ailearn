# -*- coding: utf-8 -*-
"""M2 任务引擎冒烟：状态机 + 会话生成/迁移链 + WS 广播。
注意：本脚本必须放在 backend 目录之外运行，避免触发 uvicorn reload。
"""
import asyncio
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\creategame\AI学\backend")

DB = r"C:\creategame\AI学\backend\data\ailearn.db"
BASE = "http://127.0.0.1:8000/api/v1"
now = datetime.now()


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def ok(label, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + label + ((" | " + str(extra)) if extra else ""))


def set_item_time(item_id, start, end):
    con = sqlite3.connect(DB)
    con.execute("update schedule_items set start_time=?, end_time=? where id=?", (start, end, item_id))
    con.commit()
    con.close()


# ---------- Part 1: 状态机纯函数 ----------
from app.services.session_service import target_status
from app.models.enums import SessionStatus as S

base = datetime(2026, 8, 22, 19, 0)
start, end = base, base + timedelta(minutes=90)
ok("scheduled (before -15min)", target_status(base - timedelta(minutes=20), start, end) == S.SCHEDULED)
ok("pre_class (-10min)", target_status(base - timedelta(minutes=10), start, end) == S.PRE_CLASS)
ok("in_class (start+10m)", target_status(base + timedelta(minutes=10), start, end) == S.IN_CLASS)
ok("review (end+20m)", target_status(base + timedelta(minutes=110), start, end) == S.REVIEW)
ok("overdue (end+40m, unfinished)", target_status(base + timedelta(minutes=130), start, end, has_unfinished_tasks=True) == S.OVERDUE)
ok("done (end+40m, finished)", target_status(base + timedelta(minutes=130), start, end, has_unfinished_tasks=False) == S.DONE)

# ---------- Part 2: 会话生成 + 迁移链 ----------
from app.core.db import SessionLocal
from app.services.scheduler import tick_once

# 加今天的课（now+5min 开始 → 应处于 pre_class 窗口）
s, _ = api("GET", "/courses")
courses = _ if isinstance(_, list) else []
ds = next(c for c in courses if c["subject_code"] == "ds")
today = datetime.now().date()
weekday = today.weekday()
soon = (now + timedelta(minutes=5)).strftime("%H:%M:%S")
end_soon = (now + timedelta(minutes=95)).strftime("%H:%M:%S")
s, _ = api("POST", "/schedule", {"course_id": ds["id"], "weekday": weekday, "start_time": soon, "end_time": end_soon})
item_id = _["id"]

asyncio.run(tick_once())
s, today_sessions = api("GET", "/sessions/today")
session = next(x for x in today_sessions if x["course_name"] == ds["name"])
ok("session generated for today", s == 200 and session["date"] == str(today))
ok("status pre_class after tick", session["status"] == S.PRE_CLASS, session["status"])

# 任务 CRUD
s, task = api("POST", f"/sessions/{session['id']}/tasks", {"type": "read", "title": "冒烟任务A", "est_minutes": 15})
ok("task created", s == 201 and task["status"] == "todo")
s, task = api("POST", f"/tasks/{task['id']}/complete")
ok("task completed", s == 200 and task["status"] == "done")

# 迁移：改时间为过去 → in_class
set_item_time(item_id, (now - timedelta(minutes=10)).strftime("%H:%M:%S"), (now + timedelta(minutes=30)).strftime("%H:%M:%S"))
asyncio.run(tick_once())
s, today_sessions = api("GET", "/sessions/today")
session = next(x for x in today_sessions if x["course_id"] == ds["id"])
ok("status in_class after move", session["status"] == S.IN_CLASS, session["status"])

# 迁移：过 end+30 → 无未完成任务 → done
set_item_time(item_id, (now - timedelta(minutes=60)).strftime("%H:%M:%S"), (now - timedelta(minutes=45)).strftime("%H:%M:%S"))
asyncio.run(tick_once())
con = sqlite3.connect(DB)
print("[debug] tasks now:", con.execute("select id, status from tasks where session_id=?", (session["id"],)).fetchall())
print("[debug] session status:", con.execute("select status from study_sessions where id=?", (session["id"],)).fetchone())
con.close()
s, today_sessions = api("GET", "/sessions/today")
session = next(x for x in today_sessions if x["course_id"] == ds["id"])
ok("status done (tasks finished)", session["status"] == S.DONE, session["status"])

# 迁移：加未完成任务再过期 → overdue
api("POST", f"/sessions/{session['id']}/tasks", {"type": "think", "title": "未完成任务", "est_minutes": 10})
asyncio.run(tick_once())
s, today_sessions = api("GET", "/sessions/today")
session = next(x for x in today_sessions if x["course_id"] == ds["id"])
ok("status overdue (unfinished)", session["status"] == S.OVERDUE, session["status"])

# ---------- Part 3: WS 广播（依赖服务器进程的真实调度器 tick，等待其下一个周期） ----------
async def ws_probe():
    from websockets.asyncio.client import connect

    # 先重置会话状态，让服务器下一次 tick 产生变更并广播
    con = sqlite3.connect(DB)
    con.execute("update study_sessions set status='scheduled' where id=?", (session["id"],))
    con.commit()
    con.close()
    async with connect("ws://127.0.0.1:8000/api/v1/ws") as ws:
        got = []
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=70)
            got.append(json.loads(msg))
        except asyncio.TimeoutError:
            pass
        return got

events = asyncio.run(ws_probe())
ok("ws broadcast received", len(events) > 0, events[0] if events else None)
if events:
    ok("ws event shape",
       events[0].get("type") == "session_status_changed" and "status" in events[0]
       and events[0].get("session_id") == session["id"])

# 清理冒烟课表项
api("DELETE", f"/schedule/{item_id}")
print("done")