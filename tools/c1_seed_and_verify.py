# -*- coding: utf-8 -*-
"""C1 判卷流验证：手工题目 → 作答 → feedback 块。"""
import json
import sqlite3
import urllib.error
import urllib.request

DB = r"C:\creategame\AI学\backend\data\ailearn.db"
BASE = "http://127.0.0.1:8000/api/v1"

con = sqlite3.connect(DB)
node_id = con.execute("select id from knowledge_nodes where level=3 limit 1").fetchone()[0]
cur = con.execute(
    "insert into quiz_questions (node_id, difficulty, qtype, payload_json, created_at) "
    "values (?,?,?,?,datetime('now'))",
    (
        node_id,
        2,
        "choice",
        json.dumps(
            {
                "question": "测试：平衡因子取值",
                "options": ["A.-1,0,1", "B.0,1,2", "C.-2,-1,0"],
                "answer": "A",
                "explain": "平衡因子为左右子树高度差，取值 -1/0/1",
            }
        ),
    ),
)
qid = cur.lastrowid
con.execute(
    "update conversations set active_quiz_id=? "
    "where id=(select max(id) from conversations where mode='classroom')",
    (qid,),
)
con.commit()
print("seeded: qid =", qid, "node =", node_id)
con.close()


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


s, body = post("/classroom/interact", {"content": "A"})
print("== correct answer ==")
print("status:", s)
print(body[:700])

s2, body2 = post("/classroom/interact", {"content": "C"})
print("== wrong answer (no active quiz -> explain flow, no key -> guard) ==")
print("status:", s2)
print(body2[:300])