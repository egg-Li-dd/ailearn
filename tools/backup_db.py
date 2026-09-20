"""数据库备份工具：备份 ailearn.db 到 backup 目录，保留最近 N 份。

用法：
    python tools/backup_db.py              # 备份一次
    python tools/backup_db.py --keep 10    # 保留最近 10 份
    python tools/backup_db.py --restore backup_xxx.db  # 恢复指定备份
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录（tools/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "backend" / "data" / "ailearn.db"
BACKUP_DIR = PROJECT_ROOT / "backend" / "data" / "backups"

DEFAULT_KEEP = 20


def backup(keep: int = DEFAULT_KEEP) -> Path:
    """备份数据库，返回备份文件路径。"""
    if not DB_PATH.exists():
        print(f"错误：数据库文件不存在：{DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"ailearn_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_path)
    print(f"已备份：{backup_path} ({backup_path.stat().st_size / 1024:.1f} KB)")

    # 清理旧备份
    backups = sorted(BACKUP_DIR.glob("ailearn_*.db"), reverse=True)
    if len(backups) > keep:
        for old in backups[keep:]:
            old.unlink()
            print(f"已清理旧备份：{old.name}")

    return backup_path


def restore(backup_name: str) -> None:
    """从备份恢复数据库。"""
    backup_path = Path(backup_name)
    if not backup_path.is_absolute():
        backup_path = BACKUP_DIR / backup_name

    if not backup_path.exists():
        print(f"错误：备份文件不存在：{backup_path}")
        sys.exit(1)

    # 恢复前自动备份当前数据库
    if DB_PATH.exists():
        safety = backup(keep=DEFAULT_KEEP + 1)
        print(f"恢复前已自动备份当前数据库：{safety.name}")

    shutil.copy2(backup_path, DB_PATH)
    print(f"已恢复：{backup_path.name} -> {DB_PATH}")


def list_backups() -> None:
    """列出所有备份。"""
    if not BACKUP_DIR.exists():
        print("暂无备份")
        return
    backups = sorted(BACKUP_DIR.glob("ailearn_*.db"), reverse=True)
    if not backups:
        print("暂无备份")
        return
    print(f"备份目录：{BACKUP_DIR}")
    print(f"共 {len(backups)} 份备份：")
    for b in backups:
        mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size = b.stat().st_size / 1024
        print(f"  {b.name}  ({mtime}, {size:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="ai学 数据库备份工具")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"保留备份数量（默认 {DEFAULT_KEEP}）")
    parser.add_argument("--restore", type=str, help="从指定备份恢复（文件名或路径）")
    parser.add_argument("--list", action="store_true", help="列出所有备份")
    args = parser.parse_args()

    if args.list:
        list_backups()
    elif args.restore:
        restore(args.restore)
    else:
        backup(args.keep)


if __name__ == "__main__":
    main()
