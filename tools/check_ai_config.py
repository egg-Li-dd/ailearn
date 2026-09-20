# -*- coding: utf-8 -*-
"""AI 配置保存链路检查。"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, None


s, cfg = req("GET", "/ai/config")
print("GET config:", s, json.dumps(cfg, ensure_ascii=False))

s, r = req(
    "PUT", "/ai/config",
    {"base_url": "https://opencode.ai/zen/go/v1", "api_key": "sk-test-12345",
     "model": "deepseek-v4-flash", "temperature": 0.7},
)
print("PUT with key:", s, json.dumps(r, ensure_ascii=False))

s, cfg2 = req("GET", "/ai/config")
print("GET after save:", s, json.dumps(cfg2, ensure_ascii=False))

s, r = req(
    "PUT", "/ai/config",
    {"base_url": "https://opencode.ai/zen/go/v1", "api_key": "",
     "model": "deepseek-v4-flash", "temperature": 0.7},
)
print("PUT clear key:", s, json.dumps(r, ensure_ascii=False))