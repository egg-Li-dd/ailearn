"""
为当当用户的章节级知识点（level=2）生成 AI 摘要。
共 39 个章节：数学分析22章 + 高等代数10章 + 英语一7模块。
逐个生成，每个生成后立即保存，支持断点续传。
"""
import asyncio
import sqlite3
import sys
import os
from datetime import datetime

# 确保能导入后端模块
sys.path.insert(0, r"C:\creategame\AI学\backend")
os.chdir(r"C:\creategame\AI学\backend")

from app.services.ai_gateway import chat_once

DB_PATH = r"C:\creategame\AI学\backend\data\users\dangdang.db"

COURSE_NAMES = {1: "数学分析", 2: "高等代数", 3: "英语一"}


def build_prompt(course_name, chapter_name, children_names):
    """构建生成摘要的 prompt。"""
    children_text = "\n".join([f"- {c}" for c in children_names[:15]]) if children_names else "（无小节信息）"
    if len(children_names) > 15:
        children_text += f"\n... 等共 {len(children_names)} 个小节"

    return f"""请为以下考研/大学数学课程的章节生成一段简洁的学习摘要（80-150字）。

课程：{course_name}
章节：{chapter_name}

该章节包含以下小节：
{children_text}

要求：
1. 概括本章的核心内容和学习重点
2. 指出本章在整个课程中的地位和作用
3. 提及关键概念、定理或方法（如有）
4. 语言简洁，适合作为学习导航提示
5. 直接输出摘要内容，不要加标题或前缀"""


async def generate_summary(course_name, chapter_name, children_names):
    """调用 AI 生成单章摘要。"""
    prompt = build_prompt(course_name, chapter_name, children_names)
    messages = [{"role": "user", "content": prompt}]
    try:
        result = await chat_once(messages, model=None)
        return result.strip()
    except Exception as e:
        print(f"    AI 调用失败: {e}")
        return None


async def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 获取所有 level=2 的章节节点
    cursor.execute(
        """SELECT id, subject_id, name, parent_id 
           FROM knowledge_nodes 
           WHERE level = 2 
           ORDER BY subject_id, sort, id"""
    )
    chapters = cursor.fetchall()
    print(f"共 {len(chapters)} 个章节需要生成摘要")

    # 统计已完成的
    cursor.execute(
        "SELECT COUNT(*) FROM knowledge_nodes WHERE level=2 AND summary IS NOT NULL AND summary != ''"
    )
    done_count = cursor.fetchone()[0]
    print(f"已完成 {done_count} 个，待生成 {len(chapters) - done_count} 个")

    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, (node_id, subject_id, chapter_name, parent_id) in enumerate(chapters):
        course_name = COURSE_NAMES.get(subject_id, f"课程{subject_id}")

        # 检查是否已有摘要
        cursor.execute("SELECT summary FROM knowledge_nodes WHERE id=?", (node_id,))
        existing = cursor.fetchone()[0]
        if existing and existing.strip():
            print(f"[{idx+1}/{len(chapters)}] 跳过（已有摘要）: {course_name} - {chapter_name}")
            skip_count += 1
            continue

        # 获取该章节的子节点名称（用于上下文）
        cursor.execute(
            "SELECT name FROM knowledge_nodes WHERE parent_id=? ORDER BY sort, id",
            (node_id,)
        )
        children = [row[0] for row in cursor.fetchall()]

        print(f"[{idx+1}/{len(chapters)}] 生成中: {course_name} - {chapter_name} ({len(children)} 小节)")

        # 调用 AI 生成摘要
        summary = await generate_summary(course_name, chapter_name, children)

        if summary:
            # 保存到数据库
            cursor.execute(
                "UPDATE knowledge_nodes SET summary=?, updated_at=? WHERE id=?",
                (summary, datetime.now().isoformat(), node_id)
            )
            conn.commit()
            success_count += 1
            # 打印摘要前 60 字
            preview = summary[:60] + "..." if len(summary) > 60 else summary
            print(f"    ✓ 摘要: {preview}")
        else:
            fail_count += 1
            print(f"    ✗ 生成失败")

        # 每 5 个暂停一下，避免限流
        if (idx + 1) % 5 == 0 and idx < len(chapters) - 1:
            print("    （暂停 2 秒，避免限流...）")
            await asyncio.sleep(2)

    conn.close()

    print(f"\n=== 生成完成 ===")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  跳过: {skip_count}")
    print(f"  总计: {len(chapters)}")


if __name__ == "__main__":
    asyncio.run(main())
