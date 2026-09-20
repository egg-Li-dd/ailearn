"""
导入 408 知识网站的知识树到 AI学 知识库。

用法：
    cd backend
    python scripts/import_408_knowledge.py [--json <path>] [--dry-run]

数据来源：C:/creategame/408知识/knowledge_export.json
映射关系：
    Book        -> Course + KnowledgeNode(level=1, 根节点)
    Chapter     -> KnowledgeNode(level=2)
    Section     -> KnowledgeNode(level=3)
    KnowledgePoint -> KnowledgeNode(level=4, 叶子节点)
"""
import argparse
import json
import sys
from pathlib import Path

# 确保可以 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from app.core.db import SessionLocal, engine
from app.models.course import Course
from app.models.knowledge import KnowledgeNode

# 每本书对应的图标和颜色
BOOK_META = {
    "data-structures": {"icon": "🌲", "color": "--subj-ds", "sort": 1, "subject": "DATA_STRUCTURES"},
    "computer-organization": {"icon": "⚙️", "color": "--subj-co", "sort": 2, "subject": "COMPUTER_ORGANIZATION"},
    "operating-systems": {"icon": "🖥️", "color": "--subj-os", "sort": 3, "subject": "OPERATING_SYSTEMS"},
    "computer-network": {"icon": "🌐", "color": "--subj-cn", "sort": 4, "subject": "NETWORK"},
}

SOURCE_TAG = "import_408"


def load_knowledge(json_path: str) -> dict:
    """加载知识树 JSON。"""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def cleanup_existing(db) -> tuple[int, int]:
    """删除之前导入的节点和科目（幂等）。"""
    # 1. 删除所有 source=import_408 的知识节点
    stmt = delete(KnowledgeNode).where(KnowledgeNode.source == SOURCE_TAG)
    result = db.execute(stmt)
    nodes_deleted = result.rowcount

    # 2. 删除没有知识节点关联的导入科目（通过 subject_code 判断）
    imported_codes = [b["subject"] for b in BOOK_META.values()]
    # 实际上 Course 没有 source 字段，用 subject_code 匹配
    courses = db.execute(
        select(Course).where(Course.subject_code.in_(imported_codes))
    ).scalars().all()

    courses_deleted = 0
    for course in courses:
        # 检查该科目下是否还有非导入的知识节点
        remaining = db.execute(
            select(KnowledgeNode).where(
                KnowledgeNode.subject_id == course.id,
                KnowledgeNode.source != SOURCE_TAG,
            )
        ).first()
        if remaining is None:
            db.delete(course)
            courses_deleted += 1

    db.flush()
    return nodes_deleted, courses_deleted


def import_book(db, book: dict) -> dict:
    """导入一本书及其所有子节点。"""
    book_id = book["id"]
    meta = BOOK_META.get(book_id, {"icon": "📚", "color": None, "sort": 99})

    # 1. 创建 Course
    course = Course(
        name=book["title"],
        subject_code=book["subject"],
        color=meta["color"],
        sort=meta["sort"],
        icon=meta["icon"],
        description=book.get("subtitle", ""),
    )
    db.add(course)
    db.flush()  # 获取 course.id

    # 2. 创建根节点 KnowledgeNode (level=1)
    root_node = KnowledgeNode(
        parent_id=None,
        subject_id=course.id,
        name=book["title"],
        level=1,
        difficulty=1,
        mastery=0,
        status="untouched",
        source=SOURCE_TAG,
        summary=book.get("subtitle", ""),
        sort=0,
        icon=meta["icon"],
    )
    db.add(root_node)
    db.flush()

    stats = {"chapters": 0, "sections": 0, "points": 0}

    # 3. 递归导入章节
    for ch_idx, chapter in enumerate(book["chapters"]):
        ch_node = KnowledgeNode(
            parent_id=root_node.id,
            subject_id=course.id,
            name=chapter["title"],
            level=2,
            difficulty=1,
            mastery=0,
            status="untouched",
            source=SOURCE_TAG,
            summary=None,
            sort=ch_idx,
            icon=None,
        )
        db.add(ch_node)
        db.flush()
        stats["chapters"] += 1

        # 4. 导入小节
        for sec_idx, section in enumerate(chapter["sections"]):
            sec_node = KnowledgeNode(
                parent_id=ch_node.id,
                subject_id=course.id,
                name=section["title"],
                level=3,
                difficulty=1,
                mastery=0,
                status="untouched",
                source=SOURCE_TAG,
                summary=None,
                sort=sec_idx,
                icon=None,
            )
            db.add(sec_node)
            db.flush()
            stats["sections"] += 1

            # 5. 导入知识点
            for pt_idx, point in enumerate(section["points"]):
                pt_node = KnowledgeNode(
                    parent_id=sec_node.id,
                    subject_id=course.id,
                    name=point["title"],
                    level=4,
                    difficulty=point.get("importance", 3),
                    mastery=0,
                    status="untouched",
                    source=SOURCE_TAG,
                    summary=point.get("summary", ""),
                    sort=pt_idx,
                    icon=None,
                )
                db.add(pt_node)
                stats["points"] += 1

    db.flush()
    return {
        "course_id": course.id,
        "root_node_id": root_node.id,
        **stats,
    }


def main():
    parser = argparse.ArgumentParser(description="导入 408 知识树到 AI学 知识库")
    parser.add_argument(
        "--json",
        default=r"C:\creategame\408知识\knowledge_export.json",
        help="知识树 JSON 文件路径",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览不写入",
    )
    args = parser.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"错误：JSON 文件不存在：{json_path}")
        sys.exit(1)

    print(f"加载知识树：{json_path}")
    data = load_knowledge(str(json_path))
    books = data["books"]
    total_points = data.get("totalPoints", 0)

    print(f"共 {len(books)} 本书，{total_points} 个知识点")
    for book in books:
        ch_count = len(book["chapters"])
        sec_count = sum(len(c["sections"]) for c in book["chapters"])
        pt_count = sum(len(s["points"]) for c in book["chapters"] for s in c["sections"])
        print(f"  - {book['title']}: {ch_count}章 / {sec_count}节 / {pt_count}知识点")

    if args.dry_run:
        print("\n[dry-run] 预览模式，不写入数据库")
        return

    print("\n开始导入...")
    db = SessionLocal()
    try:
        # 1. 清理之前导入的数据
        print("清理之前导入的数据...")
        nodes_del, courses_del = cleanup_existing(db)
        print(f"  删除旧知识节点：{nodes_del}，旧科目：{courses_del}")

        # 2. 逐本导入
        all_stats = []
        for book in books:
            print(f"导入：{book['title']}...", end=" ")
            stats = import_book(db, book)
            all_stats.append((book["title"], stats))
            print(f"✓ ({stats['chapters']}章/{stats['sections']}节/{stats['points']}知识点)")

        # 3. 提交
        db.commit()
        print("\n导入完成！")

        # 4. 汇总
        total_ch = sum(s["chapters"] for _, s in all_stats)
        total_sec = sum(s["sections"] for _, s in all_stats)
        total_pt = sum(s["points"] for _, s in all_stats)
        print(f"\n汇总：")
        print(f"  科目：{len(all_stats)}")
        print(f"  章节：{total_ch}")
        print(f"  小节：{total_sec}")
        print(f"  知识点：{total_pt}")
        print(f"  总节点数：{len(all_stats) + total_ch + total_sec + total_pt}")

    except Exception as e:
        db.rollback()
        print(f"\n导入失败，已回滚：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
