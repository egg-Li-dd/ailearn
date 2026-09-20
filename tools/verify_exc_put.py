# -*- coding: utf-8 -*-
"""例外 PUT 端点验证。"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, None


s, ex = req("POST", "/schedule/exceptions",
            {"date": "2026-09-05", "action": "add", "course_id": 1,
             "start_time": "10:00", "end_time": "11:30"})
print("create:", s, ex and ex["id"])
if s == 201:
    eid = ex["id"]
    s, up = req("PUT", f"/schedule/exceptions/{eid}",
                {"action": "remove", "course_id": None, "start_time": None, "end_time": None})
    print("update to remove:", s, up)
    s, _ = req("DELETE", f"/schedule/exceptions/{eid}")
    print("delete:", s)