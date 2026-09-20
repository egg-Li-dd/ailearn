# -*- coding: utf-8 -*-
import json
import sqlite3
import urllib.error
import urllib.request

con = sqlite3.connect(r"C:\creategame\AI学\backend\data\ailearn.db")
qid = con.execute("select id from review_queue where status='open' limit 1").fetchone()[0]
con.close()
print("queue id:", qid)

data = json.dumps({"correct": True}).encode()
req = urllib.request.Request(
    f"http://127.0.0.1:8000/api/v1/review/{qid}/complete",
    data=data, method="POST", headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print("resp:", r.read().decode()[:300])
except urllib.error.HTTPError as e:
    print("err status:", e.code)
    print("err body:", e.read().decode()[:500])