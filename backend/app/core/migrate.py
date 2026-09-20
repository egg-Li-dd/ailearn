"""轻量迁移：SQLite 加列（model 变更后首次启动执行）。"""
import sqlite3
import logging

from .config import SQLALCHEMY_DATABASE_URL

logger = logging.getLogger("ailearn.migrate")

_ALTERS: dict[str, list[str]] = {
    "conversations": [
        "ALTER TABLE conversations ADD COLUMN active_quiz_id INTEGER",
        "ALTER TABLE conversations ADD COLUMN mainline_json TEXT",
        "ALTER TABLE conversations ADD COLUMN active_quiz_session_id INTEGER",
        "ALTER TABLE conversations ADD COLUMN course_id INTEGER",
    ],
    "messages": [
        "ALTER TABLE messages ADD COLUMN type VARCHAR(16) NOT NULL DEFAULT 'legacy'",
    ],
    "quiz_answers": [
        "ALTER TABLE quiz_answers ADD COLUMN session_id INTEGER",
        "ALTER TABLE quiz_answers ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1",
    ],
    # === 管理台重构新增字段 ===
    "courses": [
        "ALTER TABLE courses ADD COLUMN icon VARCHAR(32)",
        "ALTER TABLE courses ADD COLUMN description TEXT",
        "ALTER TABLE courses ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN target_days INTEGER",
        "ALTER TABLE courses ADD COLUMN goal_start_date DATE",
    ],
    "schedule_items": [
        "ALTER TABLE schedule_items ADD COLUMN teacher VARCHAR(64)",
        "ALTER TABLE schedule_items ADD COLUMN classroom VARCHAR(64)",
        "ALTER TABLE schedule_items ADD COLUMN week_type VARCHAR(8) NOT NULL DEFAULT 'all'",
        "ALTER TABLE schedule_items ADD COLUMN color_override VARCHAR(16)",
        "ALTER TABLE schedule_items ADD COLUMN sort INTEGER NOT NULL DEFAULT 0",
    ],
    "schedule_exceptions": [
        "ALTER TABLE schedule_exceptions ADD COLUMN reason VARCHAR(256)",
        "ALTER TABLE schedule_exceptions ADD COLUMN repeat_type VARCHAR(16) NOT NULL DEFAULT 'none'",
        "ALTER TABLE schedule_exceptions ADD COLUMN repeat_config TEXT",
        "ALTER TABLE schedule_exceptions ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
    ],
    "knowledge_nodes": [
        "ALTER TABLE knowledge_nodes ADD COLUMN sort INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE knowledge_nodes ADD COLUMN icon VARCHAR(32)",
        "ALTER TABLE knowledge_nodes ADD COLUMN notes TEXT",
        "ALTER TABLE knowledge_nodes ADD COLUMN prerequisites TEXT",
    ],
    # === FSRS 复习调度（手机 App 更新方案） ===
    "review_queue": [
        "ALTER TABLE review_queue ADD COLUMN fsrs_d FLOAT",
        "ALTER TABLE review_queue ADD COLUMN fsrs_s FLOAT",
        "ALTER TABLE review_queue ADD COLUMN fsrs_state VARCHAR(16) DEFAULT 'learning'",
        "ALTER TABLE review_queue ADD COLUMN fsrs_step INTEGER DEFAULT 0",
        "ALTER TABLE review_queue ADD COLUMN reps INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE review_queue ADD COLUMN lapses INTEGER NOT NULL DEFAULT 0",
    ],
    # === 任务-检测闭环 ===
    "tasks": [
        "ALTER TABLE tasks ADD COLUMN quiz_session_id INTEGER",
        "ALTER TABLE tasks ADD COLUMN pass_score INTEGER NOT NULL DEFAULT 80",
        "ALTER TABLE tasks ADD COLUMN actual_score INTEGER",
        "ALTER TABLE tasks ADD COLUMN passed BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN completion INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN best_score INTEGER",
        "ALTER TABLE tasks ADD COLUMN score_history TEXT",
        "ALTER TABLE tasks ADD COLUMN completed_by_mastery BOOLEAN NOT NULL DEFAULT 0",
    ],
    # === 多用户物理分库：users 表扩展 ===
    "users": [
        "ALTER TABLE users ADD COLUMN username VARCHAR(32)",
        "ALTER TABLE users ADD COLUMN nickname VARCHAR(32) DEFAULT ''",
        "ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'",
        "ALTER TABLE users ADD COLUMN db_key VARCHAR(32)",
        "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
    ],
    # === 多用户：全局表加 user_key 用于统计 ===
    "ai_call_logs": [
        "ALTER TABLE ai_call_logs ADD COLUMN user_key VARCHAR(32)",
    ],
    "background_tasks": [
        "ALTER TABLE background_tasks ADD COLUMN user_key VARCHAR(32)",
    ],
    # === AI 通道用户隔离：全局通道(user_key=NULL) + 用户私有通道 ===
    "ai_channels": [
        "ALTER TABLE ai_channels ADD COLUMN user_key VARCHAR(32)",
    ],
}


def run_migrations() -> None:
    """对已存在的表补齐新列；建表逻辑交给 create_all。"""
    path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
    con = sqlite3.connect(path)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, stmts in _ALTERS.items():
            if table not in tables:
                continue
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            for stmt in stmts:
                col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
                if col not in cols:
                    con.execute(stmt)
                    logger.info("migrate: %s add column %s", table, col)
        con.commit()
    finally:
        con.close()
