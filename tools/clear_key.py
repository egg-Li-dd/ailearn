# -*- coding: utf-8 -*-
import sqlite3

con = sqlite3.connect(r"C:\creategame\AI学\backend\data\ailearn.db")
con.execute("delete from user_settings where key = 'ai.api_key'")
con.commit()
print("remaining ai settings:", con.execute("select * from user_settings").fetchall())
con.close()