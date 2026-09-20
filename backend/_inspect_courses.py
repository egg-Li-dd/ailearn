"""查看课程表和高数二相关的残留数据。"""
import sqlite3

DB_PATH = r"C:\creategame\AI学\backend\data\ailearn.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 查看课程表
print("=== courses 表（所有课程）===")
cursor.execute("PRAGMA table_info(courses)")
cols = [c[1] for c in cursor.fetchall()]
print(f"列: {cols}")
cursor.execute("SELECT * FROM courses ORDER BY id")
rows = cursor.fetchall()
for r in rows:
    d = dict(zip(cols, r))
    print(f"  id={d.get('id')}, name={d.get('name')}, desc={str(d.get('description',''))[:40]}, created={d.get('created_at')}")

# 查看每个课程的知识点数量
print("\n=== 各课程知识点数量 ===")
cursor.execute("""
    SELECT c.id, c.name, COUNT(k.id) as kn_count
    FROM courses c
    LEFT JOIN knowledge_nodes k ON k.subject_id = c.id
    GROUP BY c.id, c.name
    ORDER BY c.id
""")
for r in cursor.fetchall():
    print(f"  course_id={r[0]}, name={r[1]}, 知识点数={r[2]}")

# 查看每个课程的题目数量
print("\n=== 各课程题目数量 ===")
cursor.execute("""
    SELECT c.id, c.name, COUNT(q.id) as q_count
    FROM courses c
    LEFT JOIN knowledge_nodes k ON k.subject_id = c.id
    LEFT JOIN quiz_questions q ON q.node_id = k.id
    GROUP BY c.id, c.name
    ORDER BY c.id
""")
for r in cursor.fetchall():
    print(f"  course_id={r[0]}, name={r[1]}, 题目数={r[2]}")

# 查看每个课程的小测数量
print("\n=== 各课程小测数量 ===")
try:
    cursor.execute("""
        SELECT c.id, c.name, COUNT(qs.id) as s_count
        FROM courses c
        LEFT JOIN quiz_sessions qs ON qs.course_id = c.id
        GROUP BY c.id, c.name
        ORDER BY c.id
    """)
    for r in cursor.fetchall():
        print(f"  course_id={r[0]}, name={r[1]}, 小测数={r[2]}")
except Exception as e:
    print(f"  查询失败: {e}")

# 查看每个课程的任务数量
print("\n=== 各课程任务数量 ===")
try:
    cursor.execute("""
        SELECT c.id, c.name, COUNT(t.id) as t_count
        FROM courses c
        LEFT JOIN tasks t ON t.course_id = c.id
        GROUP BY c.id, c.name
        ORDER BY c.id
    """)
    for r in cursor.fetchall():
        print(f"  course_id={r[0]}, name={r[1]}, 任务数={r[2]}")
except Exception as e:
    print(f"  查询失败: {e}")

# 查看知识点名称中包含"高数"或"数学"或"二"的
print("\n=== 知识点名称包含'数学'或'高数'或'二'的（前30）===")
cursor.execute("""
    SELECT id, name, subject_id, level FROM knowledge_nodes
    WHERE name LIKE '%数学%' OR name LIKE '%高数%' OR name LIKE '%二%'
    ORDER BY id LIMIT 30
""")
for r in cursor.fetchall():
    print(f"  id={r[0]}, name={r[1]}, subject_id={r[2]}, level={r[3]}")

conn.close()
