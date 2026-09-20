# -*- coding: utf-8 -*-
import sqlite3

con = sqlite3.connect(r"C:\creategame\AI学\backend\data\ailearn.db")
con.execute("delete from tasks where id in (1,2)")
rows = con.execute("select id from tasks order by id").fetchall()
for i, (tid,) in enumerate(rows, start=1):
    con.execute("update tasks set seq=? where id=?", (i, tid))
con.commit()
for r in con.execute("select id, seq, type, title, status from tasks order by seq"):
    print(r)
con.close()