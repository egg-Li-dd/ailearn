# -*- coding: utf-8 -*-
"""M5 出题闭环冒烟：客观题判定链 + 沉淀确认链 + 复习队列链。"""
import json
import sqlite3
import urllib.request
from datetime import datetime, timedelta

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"C:\creategame\AI学\backend\data\ailearn.db"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
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


def direct_sql(sql, args=()):
    con = sqlite3.connect(DB)
    con.execute(sql, args)
    con.commit()
    con.close()


# 准备：找一个叶子知识点作为题目载体
s, tree = api("GET", "/knowledge/tree")
roots = tree if isinstance(tree, list) else []
leaf = None


def find_leaf(nodes):
    for n in nodes:
        if n["children"]:
            r = find_leaf(n["children"])
            if r:
                return r
        if n["level"] == 3:
            return n
    return None


leaf = find_leaf(roots)
ok("leaf node exists", leaf is not None, leaf and leaf["name"])

# 1. 出题（无 key → 守卫错误；有 key → 生成）
s, q = api("POST", f"/knowledge/nodes/{leaf['id']}/quiz")
if s == 201:
    ok("quiz generated (ai)", q["question"] != "", q["qtype"])
    qid = q["id"]
else:
    ok("quiz guarded without key", "detail" in (q or {}) and "Key" in str(q), q)
    # 手工插入一条客观题用于测试判定链路
    con = sqlite3.connect(DB)
    cur = con.execute(
        "insert into quiz_questions (node_id, difficulty, qtype, payload_json, created_at) values (?,?,?,?,?)",
        (leaf["id"], 2, "choice",
         json.dumps({"question": "测试题", "options": ["A.1", "B.2"], "answer": "A", "explain": "解析"}),
         datetime.now()),
    )
    qid = cur.lastrowid
    con.commit()
    con.close()

# 2. 答对 → 掌握度上升
s, ans = api("POST", "/quiz/answer", {"question_id": qid, "user_answer": "A"})
ok("answer correct", s == 200 and ans.get("correct") is True, ans)
s, node = api("GET", f"/knowledge/nodes/{leaf['id']}")
ok("mastery raised after correct", node["mastery"] > (leaf["mastery"] if leaf else 0), node["mastery"])

# 3. 答错 → 掌握度下降
q2id = qid
if s == 200 and ans.get("correct") is True:
    s, ans2 = api("POST", "/quiz/answer", {"question_id": qid, "user_answer": "B"})
    ok("answer wrong", s == 200 and ans2.get("correct") is False)
    s, node2 = api("GET", f"/knowledge/nodes/{leaf['id']}")
    ok("mastery dropped after wrong", node2["mastery"] < node["mastery"], f"{node['mastery']}->{node2['mastery']}")

# 4. 沉淀：无 key 时手动造建议 → 接受 → 建点 + 队列
con = sqlite3.connect(DB)
con.execute("insert into conversations (mode, started_at) values ('free', ?)", (datetime.now(),))
conv_id = con.execute("select last_insert_rowid()").fetchone()[0]
con.execute(
    "insert into sediment_suggestions (conversation_id, kind, content, status) values (?,?,?, 'pending')",
    (conv_id, "conclusion", "队列先进先出：FIFO 用队列，LIFO 用栈",),
)
sug_id = con.execute("select last_insert_rowid()").fetchone()[0]
con.commit()
con.close()

s, acc = api("POST", f"/sediments/{sug_id}/accept")
ok("sediment accepted -> node", s == 201 and acc.get("node_id"), acc)

# 队列应写入 1/3/7 天三条（查表验证，因 today 只返回到期项）
con = sqlite3.connect(DB)
rows = con.execute(
    "select due_at, status from review_queue where node_id=? order by due_at",
    (acc["node_id"],),
).fetchall()
ok("review queue created 1/3/7 days", len(rows) == 3, rows)
# 前移到已到期，驱动 today + complete 链路
con.execute("update review_queue set due_at=? where node_id=?", (datetime.now() - timedelta(hours=1), acc["node_id"]))
con.commit()
con.close()

s, queue = api("GET", "/review/today")
ok("review today returns due items", isinstance(queue, list) and len(queue) == 3, [q["node_name"] for q in queue])
if isinstance(queue, list) and queue:
    qitem = queue[0]
    s, done = api("POST", f"/review/{qitem['id']}/complete", {"correct": True})
    ok("review complete updates mastery", s == 200 and "mastery" in done, done)
    s, queue2 = api("GET", "/review/today")
    ok("review item closed", len([q for q in queue2 if q["id"] == qitem["id"]]) == 0)

print("done")