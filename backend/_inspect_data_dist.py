import sqlite3

DB_PATH = r"C:\creategame\AI学\backend\data\ailearn.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 列出所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]

# 查看每个表的结构和记录数，以及 user_id 分布
print("=== 各表数据概览 ===")
for t in tables:
    cursor.execute(f"PRAGMA table_info({t})")
    cols = [c['name'] for c in cursor.fetchall()]
    
    cursor.execute(f"SELECT COUNT(*) as cnt FROM {t}")
    cnt = cursor.fetchone()['cnt']
    
    has_user = 'user_id' in cols
    user_dist = ""
    if has_user and cnt > 0:
        cursor.execute(f"SELECT user_id, COUNT(*) as c FROM {t} GROUP BY user_id ORDER BY c DESC")
        dist = cursor.fetchall()
        user_dist = " | user分布: " + ", ".join([f"uid={r['user_id']}:{r['c']}" for r in dist])
    
    print(f"\n[{t}] 总数={cnt} 字段={cols}{user_dist}")

# 特别查看 courses, conversations, messages, study_sessions, tasks 等核心业务表
print("\n\n=== 核心业务表详细数据 ===")
core_tables = ['courses', 'conversations', 'messages', 'study_sessions', 'tasks', 
                'quiz_sessions', 'mastery_records', 'schedule_items', 'knowledge_nodes']

for t in core_tables:
    if t in tables:
        print(f"\n--- {t} (前5条) ---")
        cursor.execute(f"SELECT * FROM {t} LIMIT 5")
        rows = cursor.fetchall()
        for r in rows:
            d = dict(r)
            # 截断长文本
            for k, v in d.items():
                if isinstance(v, str) and len(v) > 100:
                    d[k] = v[:100] + "..."
            print(f"  {d}")

conn.close()
