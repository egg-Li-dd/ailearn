# -*- coding: utf-8 -*-
"""诊断：用库中已存的 key 直接测试 opencode 官网 chat 接口。"""
import json
import sqlite3
import urllib.error
import urllib.request

DB = r"C:\creategame\AI学\backend\data\ailearn.db"

con = sqlite3.connect(DB)
rows = dict(con.execute("select key, value from user_settings").fetchall())
con.close()

key = rows.get("ai.api_key", "")
base = rows.get("ai.base_url", "")
model = rows.get("ai.model", "")
print("stored: base=%s model=%s key_len=%d key_head=%s" % (
    base, model, len(key), key[:6] + "..." if key else "(empty)"))

if not key:
    print("RESULT: key NOT saved")
elif not base:
    print("RESULT: base_url missing")
else:
    payload = json.dumps({
        "model": model or "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    }).encode()
    url = base.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            reply = data["choices"][0]["message"]["content"]
            print("RESULT: OK ->", reply[:80])
            print("models-usage:", data.get("model"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        print("RESULT: HTTP %d -> %s" % (e.code, body))
    except Exception as e:
        print("RESULT: ERR ->", e)