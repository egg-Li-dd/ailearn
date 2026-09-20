"""探查数据库结构和高数二相关残留数据。"""
import sqlite3

DB_PATH = r"C:\creategame\AI学\backend\data\ailearn.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 列出所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]
print("=== 数据库表 ===")
for t in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cursor.fetchone()[0]
        print(f"  {t}: {count} 行")
    except Exception as e:
        print(f"  {t}: 查询失败 - {e}")

# 查找课程表
print("\n=== 课程表 ===")
course_table = None
for t in tables:
    if "course" in t.lower() and "knowledge" not in t.lower():
        course_table = t
        break

if course_table:
    try:
        cursor.execute(f"SELECT * FROM [{course_table}] ORDER BY id")
        rows = cursor.fetchall()
        # 获取列名
        cursor.execute(f"PRAGMA table_info([{course_table}])")
        cols = [c[1] for c in cursor.fetchall()]
        print(f"  表名: {course_table}, 列: {cols}")
        for r in rows:
            print(f"  {dict(zip(cols, r))}")
    except Exception as e:
        print(f"  查询失败: {e}")

# 查找包含"高数"的知识点
print("\n=== 知识点表中包含'高数'或'高等数学'的 ===")
kn_table = None
for t in tables:
    if "knowledge" in t.lower() and "node" in t.lower():
        kn_table = t
        break

if kn_table:
    try:
        cursor.execute(f"PRAGMA table_info([{kn_table}])")
        cols = [c[1] for c in cursor.fetchall()]
        print(f"  表名: {kn_table}, 列: {cols}")
        cursor.execute(f"SELECT id, name, subject_id, level, mastery FROM [{kn_table}] WHERE name LIKE '%高数%' OR name LIKE '%高等数学%' ORDER BY id LIMIT 100")
        rows = cursor.fetchall()
        print(f"  共找到 {len(rows)} 条（显示前100）")
        for r in rows:
            print(f"  id={r[0]}, name={r[1]}, subject_id={r[2]}, level={r[3]}, mastery={r[4]}")
    except Exception as e:
        print(f"  查询失败: {e}")

# 查找会话表
print("\n=== 最近 20 条会话 ===")
conv_table = None
for t in tables:
    if "conversation" in t.lower() or "conv" in t.lower():
        conv_table = t
        break

if conv_table:
    try:
        cursor.execute(f"PRAGMA table_info([{conv_table}])")
        cols = [c[1] for c in cursor.fetchall()]
        print(f"  表名: {conv_table}, 列: {cols}")
        cursor.execute(f"SELECT id, title, course_id, created_at FROM [{conv_table}] ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()
        for r in rows:
            print(f"  id={r[0]}, title={r[1]}, course_id={r[2]}, created={r[3]}")
    except Exception as e:
        print(f"  查询失败: {e}")

conn.close()
