# -*- coding: utf-8 -*-
"""M4 知识库冒烟：树 CRUD + 掌握度聚合。"""
import json
import sqlite3
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"C:\creategame\AI学\backend\data\ailearn.db"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
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


def get_db():
    return sqlite3.connect(DB)


# 清理历史树
con = get_db()
con.execute("delete from mastery_records")
con.execute("delete from knowledge_nodes")
con.commit()
con.close()

# 1. 建树：科目根 → 章 → 知识点
s, c = api("GET", "/courses")
ds = next(x for x in c if x["subject_code"] == "ds")
s, root = api("POST", "/knowledge/nodes", {"subject_id": ds["id"], "name": "数据结构", "difficulty": 1})
ok("root created", s == 201 and root["level"] == 1 and root["subject_id"] == ds["id"])
s, chap = api("POST", "/knowledge/nodes", {"parent_id": root["id"], "name": "第八章 平衡二叉树", "difficulty": 3})
s, kp1 = api("POST", "/knowledge/nodes", {"parent_id": chap["id"], "name": "平衡因子", "difficulty": 2})
s, kp2 = api("POST", "/knowledge/nodes", {"parent_id": chap["id"], "name": "LL旋转", "difficulty": 4})
ok("chapter & leaves created", s == 201 and chap["level"] == 2 and kp1["level"] == 3)
s, tree = api("GET", f"/knowledge/tree?subject_id={ds['id']}")
ok("tree shape", s == 200 and tree[0]["children"][0]["children"][0]["name"] == "平衡因子")

# 2. 掌握度更新 + 父节点聚合
s, r1 = api("POST", f"/knowledge/nodes/{kp1['id']}/mastery", {"value": 60, "reason": "小测", "source": "quiz_answer"})
ok("kp mastery 60", s == 200 and r1["mastery"] == 60 and r1["status"] == "learning")
s, r2 = api("POST", f"/knowledge/nodes/{kp2['id']}/mastery", {"value": 90, "reason": "自评", "source": "self_report"})
ok("kp2 mastery 90", s == 200 and r2["mastery"] == 90)
s, chap_after = api("GET", f"/knowledge/nodes/{chap['id']}")
ok("chapter aggregated (60+90)/2=75", s == 200 and chap_after["mastery"] == 75, chap_after["mastery"])
s, root_after = api("GET", f"/knowledge/nodes/{root['id']}")
ok("root aggregated 75", s == 200 and root_after["mastery"] == 75)

# 3. 删除保护
s, _ = api("DELETE", f"/knowledge/nodes/{chap['id']}")
ok("delete chapter with children -> 409", s == 409)
s, _ = api("DELETE", f"/knowledge/nodes/{kp1['id']}")
ok("delete leaf ok", s == 204)
s, chap2 = api("POST", "/knowledge/nodes", {"parent_id": chap["id"], "name": "LR旋转", "difficulty": 4})
ok("re-create leaf", s == 201)

# 4. 掌握度流水
con = get_db()
rows = con.execute("select node_id, old_value, new_value, source from mastery_records order by id").fetchall()
ok("mastery records written", len(rows) >= 2, rows)
con.close()

# 5. import-outline（无 key 时错误提示；有 key 走 AI）
s, r = api("POST", "/knowledge/import-outline", {"subject_id": ds["id"], "text": "第一章 绪论\n第二章 线性表\n第三章 栈和队列\n第四章 串\n"})
if s == 201:
    ok("import-outline ok (ai)", len(r) > 0, [x["name"] for x in r][:4])
else:
    ok("import-outline guarded without key", "detail" in (r or {}) and "AI" in str(r), r)

print("done")