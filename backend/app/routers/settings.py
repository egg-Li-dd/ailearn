"""系统设置 API。

端点：
- GET  /api/v1/settings          获取系统配置信息
- POST /api/v1/settings/test     测试后端连接
"""
import os
import platform
import socket
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..core.basic_auth import AUTH_ENABLED, ADMIN_USER
from ..core.db import get_db, user_db_manager
from ..models import Course, KnowledgeNode, QuizQuestion

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# 公网地址优先级：环境变量 PUBLIC_BASE_URL > 自动检测局域网 IP
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


@router.get("")
async def get_settings(request: Request, db: Session = Depends(get_db)):
    """获取系统配置信息。"""
    base_url = PUBLIC_BASE_URL or f"http://{_get_local_ip()}:8000"

    # 实际统计数据
    courses_count = db.scalar(select(func.count(Course.id))) or 0
    knowledge_count = db.scalar(select(func.count(KnowledgeNode.id))) or 0
    questions_count = db.scalar(select(func.count(QuizQuestion.id))) or 0

    # 数据库路径：从当前 db 连接获取
    db_path = ""
    try:
        user_key = getattr(request.state, "user_key", None)
        if user_key:
            db_path = user_db_manager._db_path(user_key)
        else:
            db_path = str(Path("data/ailearn.db").resolve())
    except Exception:
        db_path = str(Path("data/ailearn.db").resolve())

    return {
        "system": {
            "version": "1.0.0",
            "backend_url": base_url,
            "admin_url": f"{base_url}/admin",
            "docs_url": f"{base_url}/docs",
            "is_public": bool(PUBLIC_BASE_URL),
        },
        "auth": {
            "enabled": AUTH_ENABLED,
            "username": ADMIN_USER if AUTH_ENABLED else None,
            "note": "认证已关闭，App 无需填写用户名密码" if not AUTH_ENABLED else "认证已开启，App 需填写用户名密码",
        },
        "database": {
            "type": "sqlite",
            "path": db_path,
        },
        "stats": {
            "courses": courses_count,
            "knowledge_nodes": knowledge_count,
            "questions": questions_count,
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
    }


@router.post("/test")
async def test_connection():
    """测试后端连接是否正常。"""
    return {"status": "ok", "message": "连接正常", "timestamp": _now()}


def _get_local_ip() -> str:
    """获取本机局域网 IP。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat()
