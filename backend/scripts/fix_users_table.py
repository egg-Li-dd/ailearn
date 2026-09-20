"""修复 users 表结构：重建表，device_id 改为可空，添加新字段索引。

由于 SQLite ALTER TABLE 不能修改已有列的 NOT NULL 约束，
需要通过"创建新表 → 复制数据 → 删除旧表 → 重命名"的方式重建。
"""
import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fix_users_table")

DB_PATH = r"C:\creategame\AI学\backend\data\ailearn.db"


def fix_users_table():
    con = sqlite3.connect(DB_PATH)
    try:
        # 查看当前 users 表结构
        cols = con.execute("PRAGMA table_info(users)").fetchall()
        logger.info("当前 users 表字段:")
        for c in cols:
            logger.info("  %s (type=%s, notnull=%s, default=%s)", c[1], c[2], c[3], c[4])

        # 查看现有索引
        indexes = con.execute("PRAGMA index_list(users)").fetchall()
        logger.info("当前索引: %s", indexes)

        # 备份现有数据
        rows = con.execute("SELECT * FROM users").fetchall()
        col_names = [desc[0] for desc in con.execute("SELECT * FROM users LIMIT 1").description]
        logger.info("现有用户数: %d", len(rows))

        # 关闭外键约束
        con.execute("PRAGMA foreign_keys=OFF")

        # 创建新表（和模型一致：device_id 可空，username/db_key unique）
        con.execute("""
            CREATE TABLE users_new (
                id INTEGER NOT NULL PRIMARY KEY,
                username VARCHAR(32),
                nickname VARCHAR(32) DEFAULT '',
                role VARCHAR(16) DEFAULT 'user',
                db_key VARCHAR(32),
                device_id VARCHAR(64),
                pin_hash VARCHAR(128) NOT NULL,
                token_hash VARCHAR(64),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME,
                last_login_at DATETIME
            )
        """)

        # 复制数据（只复制两表共有的字段）
        new_cols = {c[1] for c in con.execute("PRAGMA table_info(users_new)").fetchall()}
        common_cols = [c for c in col_names if c in new_cols]
        placeholders = ",".join(["?" for _ in common_cols])
        col_str = ",".join(common_cols)

        for row in rows:
            row_dict = dict(zip(col_names, row))
            values = [row_dict.get(c) for c in common_cols]
            con.execute(f"INSERT INTO users_new ({col_str}) VALUES ({placeholders})", values)

        logger.info("数据复制完成，共 %d 条", len(rows))

        # 删除旧表，重命名新表
        con.execute("DROP TABLE users")
        con.execute("ALTER TABLE users_new RENAME TO users")

        # 创建索引
        con.execute("CREATE UNIQUE INDEX ix_users_username ON users (username)")
        con.execute("CREATE UNIQUE INDEX ix_users_db_key ON users (db_key)")
        con.execute("CREATE INDEX ix_users_device_id ON users (device_id)")

        con.commit()

        # 验证
        cols = con.execute("PRAGMA table_info(users)").fetchall()
        logger.info("修复后 users 表字段:")
        for c in cols:
            logger.info("  %s (type=%s, notnull=%s)", c[1], c[2], c[3])

        rows = con.execute("SELECT id, username, nickname, role, db_key, device_id, is_active FROM users ORDER BY id").fetchall()
        logger.info("用户数据:")
        for r in rows:
            logger.info("  id=%s username=%s nickname=%s role=%s db_key=%s device_id=%s active=%s", *r)

        con.execute("PRAGMA foreign_keys=ON")
        logger.info("修复完成！")

    except Exception as e:
        con.rollback()
        logger.error("修复失败: %s", e, exc_info=True)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    fix_users_table()
