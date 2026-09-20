"""多用户物理分库数据迁移脚本。

执行内容：
1. 备份当前 ailearn.db
2. 扩展 users 表（添加 username/nickname/role/db_key/is_active/last_login_at）
3. 给现有用户记录填充新字段（id=1 设为 eggli/admin）
4. 复制 ailearn.db → users/eggli.db（egglli 的业务数据）
5. 全局库 ailearn.db 清空所有业务表数据
6. eggli.db 删除全局表（只保留业务表）
7. 验证迁移结果

使用方法：
    python backend/scripts/migrate_multiuser.py

注意：执行前请确保后端服务已停止！
"""
import os
import sys
import shutil
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

# 确保能导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import DATA_DIR, USER_DB_DIR, SQLALCHEMY_DATABASE_URL
from app.core.migrate import run_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_multiuser")

# 全局库路径
GLOBAL_DB_PATH = DATA_DIR / "ailearn.db"
# 用户库目录
USER_DB_DIR.mkdir(parents=True, exist_ok=True)

# 业务表清单（用户库保留，全局库清空）
BUSINESS_TABLES = [
    "courses", "schedule_items", "schedule_exceptions", "schedule_templates",
    "knowledge_nodes", "mastery_records", "review_queue", "course_memories",
    "conversations", "messages", "sediment_suggestions",
    "study_sessions", "tasks", "task_events",
    "quiz_questions", "quiz_sessions", "quiz_session_items", "quiz_answers",
    "user_settings",
]

# 全局表清单（用户库删除，全局库保留）
GLOBAL_TABLES = [
    "users",
    "ai_channels", "ai_call_logs", "ai_experiments", "ai_experiment_events",
    "audit_logs", "system_logs",
    "background_tasks",
]


def backup_global_db() -> Path:
    """备份全局库。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = DATA_DIR / f"ailearn.db.bak-multiuser-{timestamp}"
    shutil.copy2(GLOBAL_DB_PATH, backup_path)
    # 同时备份 wal 和 shm
    for ext in ("-wal", "-shm"):
        src = DATA_DIR / f"ailearn.db{ext}"
        if src.exists():
            shutil.copy2(src, DATA_DIR / f"ailearn.db{ext}.bak-multiuser-{timestamp}")
    logger.info("已备份全局库: %s", backup_path)
    return backup_path


def migrate_users_table():
    """扩展 users 表并填充现有用户记录。"""
    logger.info("=== 步骤 1: 扩展 users 表 ===")

    # 先运行轻量迁移（添加新列）
    run_migrations()

    con = sqlite3.connect(GLOBAL_DB_PATH)
    try:
        # 查看现有用户
        users = con.execute("SELECT id, device_id, created_at FROM users ORDER BY id").fetchall()
        logger.info("现有用户数: %d", len(users))

        for uid, device_id, created_at in users:
            if uid == 1:
                # 第一条记录设为 eggli（管理员）
                username = "eggli"
                nickname = "eggli"
                role = "admin"
                db_key = "eggli"
                is_active = 1
                logger.info("  用户 id=%d device_id=%s → eggli (admin)", uid, device_id)
            else:
                # 其他记录保留但禁用，用 device_id 生成 db_key
                safe_dev = "".join(c for c in str(device_id) if c.isalnum() or c == "_").lower()
                if not safe_dev:
                    safe_dev = f"user{uid}"
                username = f"legacy_{safe_dev}"
                nickname = f"legacy_{device_id}"
                role = "user"
                db_key = f"legacy_{safe_dev}"
                is_active = 0
                logger.info("  用户 id=%d device_id=%s → %s (disabled)", uid, device_id, username)

            con.execute(
                """UPDATE users SET username=?, nickname=?, role=?, db_key=?, is_active=?
                   WHERE id=?""",
                (username, nickname, role, db_key, is_active, uid),
            )

        con.commit()
        logger.info("users 表填充完成")

        # 验证
        rows = con.execute("SELECT id, username, nickname, role, db_key, is_active FROM users ORDER BY id").fetchall()
        for r in rows:
            logger.info("  验证: id=%s username=%s role=%s db_key=%s active=%s", *r)

    finally:
        con.close()


def create_eggli_db():
    """复制全局库为 eggli 用户库，并删除全局表。"""
    logger.info("=== 步骤 2: 创建 eggli 用户库 ===")

    eggli_db_path = USER_DB_DIR / "eggli.db"

    # 复制数据库文件
    shutil.copy2(GLOBAL_DB_PATH, eggli_db_path)
    logger.info("已复制: %s → %s", GLOBAL_DB_PATH, eggli_db_path)

    # 在 eggli.db 中删除全局表
    con = sqlite3.connect(eggli_db_path)
    try:
        # 关闭外键约束（删除表时）
        con.execute("PRAGMA foreign_keys=OFF")

        for table in GLOBAL_TABLES:
            try:
                con.execute(f"DROP TABLE IF EXISTS {table}")
                logger.info("  eggli.db 删除表: %s", table)
            except Exception as e:
                logger.warning("  删除表 %s 失败: %s", table, e)

        con.commit()

        # 验证：eggli.db 应该只剩业务表
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        logger.info("eggli.db 剩余表 (%d): %s", len(tables), sorted(tables))

        # 统计业务数据
        for table in BUSINESS_TABLES:
            if table in tables:
                cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if cnt > 0:
                    logger.info("  %s: %d 条记录", table, cnt)

    finally:
        con.close()

    logger.info("eggli 用户库创建完成: %s", eggli_db_path)


def clear_global_business_data():
    """清空全局库中的业务表数据（只保留全局表）。"""
    logger.info("=== 步骤 3: 清空全局库业务数据 ===")

    con = sqlite3.connect(GLOBAL_DB_PATH)
    try:
        con.execute("PRAGMA foreign_keys=OFF")

        for table in BUSINESS_TABLES:
            try:
                cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                con.execute(f"DELETE FROM {table}")
                logger.info("  清空 %s: 删除 %d 条记录", table, cnt)
            except Exception as e:
                logger.warning("  清空 %s 失败: %s", table, e)

        # 重置自增 ID
        try:
            con.execute("DELETE FROM sqlite_sequence WHERE name IN ({})".format(
                ",".join(f"'{t}'" for t in BUSINESS_TABLES)
            ))
        except Exception:
            pass

        con.commit()
        con.execute("PRAGMA foreign_keys=ON")

        # 验证全局库
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        logger.info("全局库剩余表 (%d): %s", len(tables), sorted(tables))

        for table in GLOBAL_TABLES:
            if table in tables:
                cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                logger.info("  %s: %d 条记录", table, cnt)

    finally:
        con.close()

    logger.info("全局库业务数据清空完成")


def verify_migration():
    """验证迁移结果。"""
    logger.info("=== 步骤 4: 验证迁移结果 ===")

    # 验证全局库
    con = sqlite3.connect(GLOBAL_DB_PATH)
    try:
        # users 表应该有 eggli admin
        eggli = con.execute("SELECT * FROM users WHERE username='eggli'").fetchone()
        assert eggli is not None, "全局库中未找到 eggli 用户"
        logger.info("✓ 全局库: eggli 用户存在")

        # 业务表应该为空
        for table in BUSINESS_TABLES:
            try:
                cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert cnt == 0, f"全局库 {table} 仍有 {cnt} 条数据"
            except sqlite3.OperationalError:
                pass  # 表不存在也算通过
        logger.info("✓ 全局库: 所有业务表已清空")

    finally:
        con.close()

    # 验证 eggli.db
    eggli_db_path = USER_DB_DIR / "eggli.db"
    assert eggli_db_path.exists(), f"eggli.db 不存在: {eggli_db_path}"

    con = sqlite3.connect(eggli_db_path)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        # 不应该有全局表
        for table in GLOBAL_TABLES:
            assert table not in tables, f"eggli.db 中仍有全局表 {table}"
        logger.info("✓ eggli.db: 无全局表")

        # 应该有业务表且有数据
        has_data = False
        for table in BUSINESS_TABLES:
            if table in tables:
                cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if cnt > 0:
                    has_data = True
        assert has_data, "eggli.db 中没有任何业务数据"
        logger.info("✓ eggli.db: 业务数据完整")

    finally:
        con.close()

    logger.info("=== 迁移验证全部通过 ===")


def main():
    logger.info("=" * 60)
    logger.info("多用户物理分库数据迁移")
    logger.info("全局库: %s", GLOBAL_DB_PATH)
    logger.info("用户库目录: %s", USER_DB_DIR)
    logger.info("=" * 60)

    # 检查后端是否在运行（简单检查端口）
    # 这里只做提醒，不强制检查

    # 1. 备份
    backup_path = backup_global_db()
    logger.info("备份文件: %s（如迁移失败可恢复）", backup_path)

    # 2. 扩展 users 表并填充
    migrate_users_table()

    # 3. 创建 eggli 用户库
    create_eggli_db()

    # 4. 清空全局库业务数据
    clear_global_business_data()

    # 5. 验证
    verify_migration()

    logger.info("")
    logger.info("=" * 60)
    logger.info("迁移完成！")
    logger.info("  - 全局库: %s（users + AI通道 + 系统日志）", GLOBAL_DB_PATH)
    logger.info("  - eggli 用户库: %s（全部业务数据）", USER_DB_DIR / "eggli.db")
    logger.info("  - 备份: %s", backup_path)
    logger.info("")
    logger.info("eggli 管理员账号: username=eggli, PIN=原设备对应PIN")
    logger.info("如需创建当当用户，启动后端后通过管理台或 API 创建")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
