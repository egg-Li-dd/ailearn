"""
将 408 导入的知识节点合并到旧科目下，删除新创建的重复 Course。

新旧科目映射：
    DATA_STRUCTURES      -> ds
    COMPUTER_ORGANIZATION -> co
    OPERATING_SYSTEMS    -> os
    NETWORK               -> net

用法：
    cd backend
    python scripts/merge_408_to_old_courses.py [--dry-run]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.models.course import Course
from app.models.knowledge import KnowledgeNode

# 新 code -> 旧 code
CODE_MAPPING = {
    "DATA_STRUCTURES": "ds",
    "COMPUTER_ORGANIZATION": "co",
    "OPERATING_SYSTEMS": "os",
    "NETWORK": "net",
}

SOURCE_TAG = "import_408"


def main():
    parser = argparse.ArgumentParser(description="合并 408 导入节点到旧科目")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total_moved = 0
        total_deleted = 0

        for new_code, old_code in CODE_MAPPING.items():
            # 查找新旧科目
            new_course = db.execute(
                select(Course).where(Course.subject_code == new_code)
            ).scalar_one_or_none()
            old_course = db.execute(
                select(Course).where(Course.subject_code == old_code)
            ).scalar_one_or_none()

            if new_course is None:
                print(f"[跳过] 新科目 {new_code} 不存在")
                continue
            if old_course is None:
                print(f"[跳过] 旧科目 {old_code} 不存在，无法合并 {new_code}")
                continue

            # 统计需要移动的节点数
            nodes_to_move = db.execute(
                select(KnowledgeNode).where(
                    KnowledgeNode.subject_id == new_course.id,
                    KnowledgeNode.source == SOURCE_TAG,
                )
            ).scalars().all()

            print(f"合并：{new_course.name} ({new_code}) -> {old_course.name} ({old_code})")
            print(f"  待移动节点：{len(nodes_to_move)} 个")

            if not args.dry_run:
                # 批量更新 subject_id
                db.execute(
                    update(KnowledgeNode)
                    .where(
                        KnowledgeNode.subject_id == new_course.id,
                        KnowledgeNode.source == SOURCE_TAG,
                    )
                    .values(subject_id=old_course.id)
                )
                db.flush()

                # 删除新科目
                db.delete(new_course)
                db.flush()

                print(f"  ✓ 已移动 {len(nodes_to_move)} 个节点，删除科目 {new_code}")

            total_moved += len(nodes_to_move)
            total_deleted += 1

        if not args.dry_run:
            db.commit()
            print(f"\n合并完成！共移动 {total_moved} 个节点，删除 {total_deleted} 个重复科目")
        else:
            print(f"\n[dry-run] 预览：将移动 {total_moved} 个节点，删除 {total_deleted} 个重复科目")

        # 验证：列出合并后的科目
        print("\n=== 合并后科目列表 ===")
        courses = db.execute(select(Course).order_by(Course.sort)).scalars().all()
        for c in courses:
            from sqlalchemy import func
            node_count = db.execute(
                select(func.count(KnowledgeNode.id)).where(
                    KnowledgeNode.subject_id == c.id
                )
            ).scalar()
            print(f"  {c.sort}. {c.name} (code={c.subject_code}, nodes={node_count})")

    except Exception as e:
        db.rollback()
        print(f"\n合并失败，已回滚：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
