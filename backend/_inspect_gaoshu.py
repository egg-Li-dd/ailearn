"""查看高数二（course_id=2）相关的所有数据范围。"""
import sqlite3

DB_PATH = r"C:\creategame\AI学\backend\data\ailearn.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

COURSE_ID = 2

print(f"=== 高数二（course_id={COURSE_ID}）相关数据统计 ===\n")

# 知识点
cursor.execute("SELECT COUNT(*) FROM knowledge_nodes WHERE subject_id=?", (COURSE_ID,))
print(f"知识点: {cursor.fetchone()[0]} 个")

# 题目（通过知识点关联）
cursor.execute("""
    SELECT COUNT(*) FROM quiz_questions q
    JOIN knowledge_nodes k ON q.node_id = k.id
    WHERE k.subject_id=?
""", (COURSE_ID,))
print(f"题目: {cursor.fetchone()[0]} 道")

# 题目答案
cursor.execute("""
    SELECT COUNT(*) FROM quiz_answers qa
    JOIN quiz_questions q ON qa.question_id = q.id
    JOIN knowledge_nodes k ON q.node_id = k.id
    WHERE k.subject_id=?
""", (COURSE_ID,))
print(f"题目答案记录: {cursor.fetchone()[0]} 条")

# 小测会话（查看表结构）
cursor.execute("PRAGMA table_info(quiz_sessions)")
qs_cols = [c[1] for c in cursor.fetchall()]
print(f"\nquiz_sessions 列: {qs_cols}")

# 查看小测会话是否有关联课程的字段
if 'course_id' in qs_cols:
    cursor.execute("SELECT COUNT(*) FROM quiz_sessions WHERE course_id=?", (COURSE_ID,))
    print(f"小测会话: {cursor.fetchone()[0]} 个")
else:
    # 通过 quiz_session_items 关联
    cursor.execute("""
        SELECT COUNT(DISTINCT qs.id) FROM quiz_sessions qs
        JOIN quiz_session_items qsi ON qsi.session_id = qs.id
        JOIN quiz_questions q ON qsi.question_id = q.id
        JOIN knowledge_nodes k ON q.node_id = k.id
        WHERE k.subject_id=?
    """, (COURSE_ID,))
    print(f"小测会话（含高数二题目）: {cursor.fetchone()[0]} 个")

# 小测题目项
cursor.execute("""
    SELECT COUNT(*) FROM quiz_session_items qsi
    JOIN quiz_questions q ON qsi.question_id = q.id
    JOIN knowledge_nodes k ON q.node_id = k.id
    WHERE k.subject_id=?
""", (COURSE_ID,))
print(f"小测题目项: {cursor.fetchone()[0]} 条")

# 任务（查看表结构）
cursor.execute("PRAGMA table_info(tasks)")
task_cols = [c[1] for c in cursor.fetchall()]
print(f"\ntasks 列: {task_cols}")

if 'course_id' in task_cols:
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE course_id=?", (COURSE_ID,))
    print(f"任务: {cursor.fetchone()[0]} 个")
elif 'subject_id' in task_cols:
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE subject_id=?", (COURSE_ID,))
    print(f"任务: {cursor.fetchone()[0]} 个")
else:
    # 通过 target_knowledge_id 关联
    cursor.execute("""
        SELECT COUNT(*) FROM tasks t
        JOIN knowledge_nodes k ON t.target_knowledge_id = k.id
        WHERE k.subject_id=?
    """, (COURSE_ID,))
    print(f"任务（关联高数二知识点）: {cursor.fetchone()[0]} 个")

# 学习会话
cursor.execute("PRAGMA table_info(study_sessions)")
ss_cols = [c[1] for c in cursor.fetchall()]
print(f"\nstudy_sessions 列: {ss_cols}")

if 'course_id' in ss_cols:
    cursor.execute("SELECT COUNT(*) FROM study_sessions WHERE course_id=?", (COURSE_ID,))
    print(f"学习会话: {cursor.fetchone()[0]} 个")

# 复习队列
cursor.execute("""
    SELECT COUNT(*) FROM review_queue rq
    JOIN knowledge_nodes k ON rq.node_id = k.id
    WHERE k.subject_id=?
""", (COURSE_ID,))
print(f"复习队列: {cursor.fetchone()[0]} 条")

# 掌握度记录
cursor.execute("""
    SELECT COUNT(*) FROM mastery_records mr
    JOIN knowledge_nodes k ON mr.node_id = k.id
    WHERE k.subject_id=?
""", (COURSE_ID,))
print(f"掌握度记录: {cursor.fetchone()[0]} 条")

# 课程记忆
cursor.execute("SELECT COUNT(*) FROM course_memories WHERE course_id=?", (COURSE_ID,))
print(f"课程记忆: {cursor.fetchone()[0]} 条")

# 会话
cursor.execute("SELECT COUNT(*) FROM conversations WHERE course_id=?", (COURSE_ID,))
print(f"会话: {cursor.fetchone()[0]} 条")

# 日程项
cursor.execute("PRAGMA table_info(schedule_items)")
si_cols = [c[1] for c in cursor.fetchall()]
print(f"\nschedule_items 列: {si_cols}")
if 'course_id' in si_cols:
    cursor.execute("SELECT COUNT(*) FROM schedule_items WHERE course_id=?", (COURSE_ID,))
    print(f"日程项: {cursor.fetchone()[0]} 条")

# 查看所有课程的题目数量对比
print("\n=== 各课程题目数量对比 ===")
cursor.execute("""
    SELECT c.id, c.name, COUNT(q.id) as q_count
    FROM courses c
    LEFT JOIN knowledge_nodes k ON k.subject_id = c.id
    LEFT JOIN quiz_questions q ON q.node_id = k.id
    GROUP BY c.id, c.name
    ORDER BY q_count DESC
""")
for r in cursor.fetchall():
    print(f"  {r[1]} (id={r[0]}): {r[2]} 题")

conn.close()
