import sqlite3
import json

DB_PATH = r"C:\creategame\AI学\backend\data\ailearn.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. 列出所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]
print("=== 所有表 ===")
for t in tables:
    print(f"  - {t}")

# 2. 查看用户表结构和数据
print("\n=== 用户相关表 ===")
for t in tables:
    if 'user' in t.lower() or 'student' in t.lower() or 'account' in t.lower():
        print(f"\n--- 表: {t} ---")
        cursor.execute(f"PRAGMA table_info({t})")
        cols = cursor.fetchall()
        for c in cols:
            print(f"  {c['name']} ({c['type']})")
        cursor.execute(f"SELECT * FROM {t} LIMIT 20")
        rows = cursor.fetchall()
        print(f"  记录数(前20): {len(rows)}")
        for r in rows:
            print(f"  {dict(r)}")

# 3. 查看 eggli 相关数据
print("\n=== 搜索 eggli 相关数据 ===")
for t in tables:
    try:
        cursor.execute(f"PRAGMA table_info({t})")
        cols = [c['name'] for c in cursor.fetchall()]
        for col in cols:
            try:
                cursor.execute(f"SELECT * FROM {t} WHERE CAST({col} AS TEXT) LIKE '%eggli%' LIMIT 5")
                rows = cursor.fetchall()
                if rows:
                    print(f"\n表 {t}.{col} 包含 eggli:")
                    for r in rows:
                        print(f"  {dict(r)}")
            except:
                pass
    except:
        pass

conn.close()
