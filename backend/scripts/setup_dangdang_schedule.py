"""
为当当用户配置每周课表。
课程：数学分析(course_id=1)、高等代数(course_id=2)、英语一(course_id=3)
设计原则：数学分析和高等代数交替重点学习，英语一每天坚持。
"""
import sqlite3
from datetime import datetime

DB_PATH = r"C:\creategame\AI学\backend\data\users\dangdang.db"

# 课表设计：weekday 0=周一, 1=周二, ..., 6=周日
# 每天 6 个时间段，每个 1.5 小时
TIME_SLOTS = [
    ("08:30", "10:00"),
    ("10:00", "11:30"),
    ("13:30", "15:00"),
    ("15:00", "16:30"),
    ("19:00", "20:30"),
    ("20:30", "22:00"),
]

# 每周课表：weekday -> [(course_id, slot_index), ...]
# 数学分析=1, 高等代数=2, 英语一=3
SCHEDULE = {
    0: [  # 周一
        (1, 0), (2, 1),  # 上午：数分、高代
        (1, 2), (2, 3),  # 下午：数分、高代
        (3, 4), (3, 5),  # 晚上：英语一
    ],
    1: [  # 周二
        (2, 0), (1, 1),  # 上午：高代、数分
        (2, 2), (1, 3),  # 下午：高代、数分
        (3, 4), (3, 5),  # 晚上：英语一
    ],
    2: [  # 周三
        (1, 0), (2, 1),  # 上午：数分、高代
        (1, 2), (2, 3),  # 下午：数分、高代
        (3, 4), (3, 5),  # 晚上：英语一
    ],
    3: [  # 周四
        (2, 0), (1, 1),  # 上午：高代、数分
        (2, 2), (1, 3),  # 下午：高代、数分
        (3, 4), (3, 5),  # 晚上：英语一
    ],
    4: [  # 周五
        (1, 0), (2, 1),  # 上午：数分、高代
        (1, 2), (2, 3),  # 下午：数分、高代
        (3, 4), (3, 5),  # 晚上：英语一
    ],
    5: [  # 周六（复习+习题）
        (1, 0), (2, 1),  # 上午：数分复习、高代复习
        (3, 2), (1, 3),  # 下午：英语复习、数分习题
        (2, 4), (3, 5),  # 晚上：高代习题、英语写作
    ],
    6: [  # 周日（预习+总结）
        (3, 0), (1, 1),  # 上午：英语阅读、数分预习
        (2, 2), (3, 3),  # 下午：高代预习、英语单词
        (1, 4), (2, 5),  # 晚上：本周总结、下周规划
    ],
}

COURSE_NAMES = {1: "数学分析", 2: "高等代数", 3: "英语一"}


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 清空旧课表
    cursor.execute("DELETE FROM schedule_items")
    deleted = cursor.rowcount
    print(f"已清空 {deleted} 条旧课表")

    # 插入新课表
    total = 0
    for weekday, items in SCHEDULE.items():
        for sort_idx, (course_id, slot_idx) in enumerate(items):
            start_time, end_time = TIME_SLOTS[slot_idx]
            cursor.execute(
                """INSERT INTO schedule_items 
                   (course_id, weekday, start_time, end_time, location, is_active, teacher, classroom, week_type, color_override, sort)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (course_id, weekday, start_time, end_time, "自习室", 1, None, None, "all", None, sort_idx)
            )
            total += 1

    conn.commit()

    # 验证
    print(f"\n已插入 {total} 条课表项")
    print("\n=== 每周课表 ===")
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for weekday in range(7):
        cursor.execute(
            "SELECT start_time, end_time, course_id FROM schedule_items WHERE weekday=? ORDER BY start_time",
            (weekday,)
        )
        items = cursor.fetchall()
        print(f"\n{weekday_names[weekday]}:")
        for item in items:
            course_name = COURSE_NAMES.get(item[2], f"course_{item[2]}")
            print(f"  {item[0]}-{item[1]} {course_name}")

    # 统计每门课每周学时
    print("\n=== 每周学时统计 ===")
    for course_id in [1, 2, 3]:
        cursor.execute(
            "SELECT COUNT(*) FROM schedule_items WHERE course_id=?",
            (course_id,)
        )
        count = cursor.fetchone()[0]
        hours = count * 1.5
        print(f"  {COURSE_NAMES[course_id]}: {count} 次课 / {hours} 小时/周")

    conn.close()
    print("\n课表配置完成！")


if __name__ == "__main__":
    main()
