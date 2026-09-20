# -*- coding: utf-8 -*-
import sys

sys.path.insert(0, r"C:\creategame\AI学\backend")
import sqlite3

from app.core.db import SessionLocal
from app.services.review import complete_item

con = sqlite3.connect(r"C:\creategame\AI学\backend\data\ailearn.db")
qid = con.execute("select id from review_queue where status='open' limit 1").fetchone()[0]
con.close()
print("queue id:", qid)

db = SessionLocal()
try:
    node = complete_item(db, qid, correct=True)
    print("ok:", node.id, node.name, node.mastery)
except Exception as e:
    import traceback

    traceback.print_exc()
finally:
    db.close()