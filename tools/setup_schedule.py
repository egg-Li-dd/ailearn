"""批量设置周课表。"""
import sqlite3

db = r'C:\creategame\AI学\backend\data\ailearn.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

# 课程ID映射
courses = {
    'ds': 1,    # 数据结构
    'math': 2,  # 高数二
    'en': 3,    # 英语
    'net': 4,   # 计算机网络
    'os': 5,    # 操作系统
    'co': 6,    # 计算机组成原理
    'pol': 7,   # 政治
}

# 时间段（每节1.5小时）
slots = [
    ('08:30', '10:00'),  # 早1
    ('10:00', '11:30'),  # 早2
    ('13:30', '15:00'),  # 午1
    ('15:00', '16:30'),  # 午2
    ('16:30', '18:00'),  # 午3
    ('19:00', '20:30'),  # 晚1
    ('20:30', '22:00'),  # 晚2
]

# 周课表：weekday 0=周一...5=周六，每天7节
schedule = {
    0: ['math', 'ds',   'math', 'co',  'os',  'en', 'pol'],   # 周一
    1: ['math', 'net',  'ds',   'math','co',  'en', 'pol'],   # 周二
    2: ['math', 'os',   'net',  'ds',  'math','en', 'co'],    # 周三
    3: ['math', 'co',   'os',   'net', 'ds',  'en', 'pol'],   # 周四
    4: ['math', 'ds',   'co',   'os',  'net', 'en', 'math'],  # 周五
    5: ['math', 'en',   'ds',   'co',  'os',  'net','pol'],   # 周六
}

# 清空旧课表
cur.execute('DELETE FROM schedule_items')
print('已清空旧课表')

# 插入新课表
inserted = 0
for weekday, day_schedule in schedule.items():
    for slot_idx, course_key in enumerate(day_schedule):
        start, end = slots[slot_idx]
        course_id = courses[course_key]
        cur.execute(
            'INSERT INTO schedule_items (course_id, weekday, start_time, end_time, is_active, week_type, sort) '
            'VALUES (?, ?, ?, ?, 1, ?, ?)',
            (course_id, weekday, start, end, 'all', slot_idx)
        )
        inserted += 1

conn.commit()

# 统计
cur.execute('''
    SELECT c.name, COUNT(s.id) as cnt
    FROM schedule_items s
    JOIN courses c ON s.course_id = c.id
    GROUP BY c.id
    ORDER BY cnt DESC
''')
print(f'\n共插入 {inserted} 节课（周一至周六，周日休息）')
print('\n各科周课时统计:')
for name, cnt in cur.fetchall():
    print(f'  {name}: {cnt} 节 ({cnt * 1.5:.1f} 小时)')

# 完整课表
weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六']
print('\n=== 完整课表 ===')
for weekday in range(6):
    cur.execute('''
        SELECT c.name, s.start_time, s.end_time
        FROM schedule_items s
        JOIN courses c ON s.course_id = c.id
        WHERE s.weekday = ?
        ORDER BY s.start_time
    ''', (weekday,))
    items = cur.fetchall()
    print(f'\n{weekday_names[weekday]}:')
    for name, start, end in items:
        print(f'  {start[:5]}-{end[:5]}  {name}')

conn.close()
print('\n完成！')
