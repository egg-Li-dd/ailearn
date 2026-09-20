"""
为当当用户的节级知识点（level=3）生成 AI 摘要。
共 198 个节：数学分析88 + 高等代数73 + 英语一37。
逐个生成，每个生成后立即保存，支持断点续传。
"""
import asyncio
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, r"C:\creategame\AI学\backend")
os.chdir(r"C:\creategame\AI学\backend")

from app.services.ai_gateway import chat_once

DB_PATH = r"C:\creategame\AI学\backend\data\users\dangdang.db"

COURSE_NAMES = {1: "数学分析", 2: "高等代数", 3: "英语一"}


def build_prompt(course_name, chapter_name, section_name, children_names):
    """构建生成摘要的 prompt。"""
    children_text = "\n".join([f"- {c}" for c in children_names[:10]]) if children_names else "（无更细子节）"
    if len(children_names) > 10:
        children_text += f"\n... 等共 {len(children_names)} 个子节"

    return f"""请为以下课程的小节生成一段简洁的学习要点摘要（50-100字）。

课程：{course_name}
章节：{chapter_name}
小节：{section_name}

该小节包含以下子知识点：
{children_text}

要求：
1. 概括本小节的核心概念、定理或方法
2. 指出学习重点和常见考点
3. 语言精炼，适合快速回顾
4. 直接输出摘要内容，不要加标题或前缀"""


async def generate_summary(course_name, chapter_name, section_name, children_names):
    """调用 AI 生成单节摘要。"""
    prompt = build_prompt(course_name, chapter_name, section_name, children_names)
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

    # 获取所有 level=3 的节节点
    cursor.execute(
        """SELECT id, subject_id, name, parent_id 
           FROM knowledge_nodes 
           WHERE level = 3 
           ORDER BY subject_id, sort, id"""
    )
    sections = cursor.fetchall()
    print(f"共 {len(sections)} 个小节需要生成摘要")

    # 统计已完成的
    cursor.execute(
        "SELECT COUNT(*) FROM knowledge_nodes WHERE level=3 AND summary IS NOT NULL AND summary != ''"
    )
    done_count = cursor.fetchone()[0]
    print(f"已完成 {done_count} 个，待生成 {len(sections) - done_count} 个")

    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, (node_id, subject_id, section_name, parent_id) in enumerate(sections):
        course_name = COURSE_NAMES.get(subject_id, f"课程{subject_id}")

        # 获取父章节名称
        cursor.execute("SELECT name FROM knowledge_nodes WHERE id=?", (parent_id,))
        parent_row = cursor.fetchone()
        chapter_name = parent_row[0] if parent_row else "未知章节"

        # 检查是否已有摘要
        cursor.execute("SELECT summary FROM knowledge_nodes WHERE id=?", (node_id,))
        existing = cursor.fetchone()[0]
        if existing and existing.strip():
            print(f"[{idx+1}/{len(sections)}] 跳过（已有摘要）: {course_name} - {section_name}")
            skip_count += 1
            continue

        # 获取该节的子节点名称（用于上下文）
        cursor.execute(
            "SELECT name FROM knowledge_nodes WHERE parent_id=? ORDER BY sort, id",
            (node_id,)
        )
        children = [row[0] for row in cursor.fetchall()]

        print(f"[{idx+1}/{len(sections)}] 生成中: {course_name} - {chapter_name} - {section_name}")

        # 调用 AI 生成摘要
        summary = await generate_summary(course_name, chapter_name, section_name, children)

        if summary:
            cursor.execute(
                "UPDATE knowledge_nodes SET summary=?, updated_at=? WHERE id=?",
                (summary, datetime.now().isoformat(), node_id)
            )
            conn.commit()
            success_count += 1
            preview = summary[:50] + "..." if len(summary) > 50 else summary
            print(f"    ✓ {preview}")
        else:
            fail_count += 1
            print(f"    ✗ 生成失败")

        # 每 10 个暂停一下，避免限流
        if (idx + 1) % 10 == 0 and idx < len(sections) - 1:
            print("    （暂停 3 秒，避免限流...）")
            await asyncio.sleep(3)

    conn.close()

    print(f"\n=== 生成完成 ===")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  跳过: {skip_count}")
    print(f"  总计: {len(sections)}")


if __name__ == "__main__":
    asyncio.run(main())
