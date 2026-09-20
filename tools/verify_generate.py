# -*- coding: utf-8 -*-
import json
import urllib.error
import urllib.request

payload = {
    "context_type": "schedule_item",
    "items": [],
    "instruction": "每周二上午9点英语一、周五晚7点半数据结构各一节课",
}
data = json.dumps(payload).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/ai/generate", data=data, method="POST",
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
        print("status:", resp.status)
        print("body:", raw.decode("utf-8", "replace")[:800])
except urllib.error.HTTPError as e:
    print("err:", e.code, e.read().decode("utf-8", "replace")[:400])
except Exception as e:
    print("exc:", e)