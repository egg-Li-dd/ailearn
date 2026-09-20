# -*- coding: utf-8 -*-
"""尝试不同 UA 绕过 Cloudflare 1010。"""
import json
import sqlite3
import urllib.error
import urllib.request

DB = r"C:\creategame\AI学\backend\data\ailearn.db"
con = sqlite3.connect(DB)
rows = dict(con.execute("select key, value from user_settings").fetchall())
con.close()
key = rows.get("ai.api_key", "")
base = rows.get("ai.base_url", "").rstrip("/")

payload = json.dumps({
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 8,
}).encode()

uas = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "opencode-zen/1.0",  # 官方 SDK 特征
]
for ua in uas:
    req = urllib.request.Request(
        base + "/chat/completions", data=payload, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key,
                 "User-Agent": ua, "Accept": "application/json",
                 "Accept-Language": "zh-CN,zh;q=0.9"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            print("UA[%s...] OK ->" % ua[:30], data["choices"][0]["message"]["content"][:60])
    except urllib.error.HTTPError as e:
        print("UA[%s...] HTTP %d" % (ua[:30], e.code), e.read().decode("utf-8", "replace")[:120])
    except Exception as e:
        print("UA[%s...] ERR" % ua[:30], str(e)[:120])