"""ai学 后端入口（M1）。"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .core.config import APP_NAME, APP_VERSION, CORS_ORIGINS_LIST, DEBUG
from .core.db import SessionLocal, init_db
from .core.basic_auth import BasicAuthMiddleware
from .core.user_middleware import UserResolverMiddleware
from .core.exceptions import register_exception_handlers
from .core.logging_config import setup_logging
from .core.logging_handler import start_log_worker, stop_log_worker
from .core.migrate import run_migrations
from .routers import ai, ai_action, asr, audit, auth, chat, classroom, course, experiment, handwrite, knowledge, knowledge_enhancer, logs, math_verifier, quiz, quiz_generator, quiz_import, quiz_session, review, session, settings, stats, tasks, version, ws, wrong_book
from .services.scheduler import start_scheduler, stop_scheduler
from .services.task_center import recover_stuck_tasks
from .services.review_scheduler import normalize_legacy_queues

logger = logging.getLogger("ailearn.main")

ADMIN_DIR = Path(__file__).resolve().parent / "static" / "admin"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB + 调度器 + 日志 worker，关闭时清理。"""
    setup_logging(logging.DEBUG if DEBUG else logging.INFO)
    logger.info("启动 %s v%s (debug=%s)", APP_NAME, APP_VERSION, DEBUG)
    run_migrations()
    init_db()
    # 旧数据归一：1/3/7 三连 → 单队列 FSRS 卡片
    db = SessionLocal()
    try:
        normalize_legacy_queues(db)
    finally:
        db.close()
    # 恢复卡住的任务（后端崩溃/重启后 pending/running 任务会永远卡住）
    recover_result = recover_stuck_tasks()
    if recover_result.get("pending") or recover_result.get("running"):
        logger.info("已恢复卡住任务: pending=%d, running=%d", recover_result.get("pending", 0), recover_result.get("running", 0))
    start_scheduler()
    start_log_worker()
    logger.info("初始化完成，服务就绪")
    yield
    stop_scheduler()
    stop_log_worker()
    logger.info("服务已关闭")


app = FastAPI(title=APP_NAME, version=APP_VERSION, debug=DEBUG, lifespan=lifespan)

# CORS：局域网阶段默认全开，可通过 AILEARN_CORS_ORIGINS 环境变量收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS_LIST,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Basic Auth：保护管理台和 API（Funnel 暴露公网时必需）
app.add_middleware(BasicAuthMiddleware)

# 用户解析：从 token / X-User-Key 识别当前用户，注入 request.state
app.add_middleware(UserResolverMiddleware)

# 全局异常处理
register_exception_handlers(app)

# 路由注册
app.include_router(ai.router)
app.include_router(ai_action.router)
app.include_router(asr.router)
app.include_router(audit.router)
app.include_router(auth.router)
app.include_router(course.router)
app.include_router(experiment.router)
app.include_router(handwrite.router)
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(classroom.router)
app.include_router(knowledge.router)
app.include_router(knowledge_enhancer.router)
app.include_router(math_verifier.router)
app.include_router(wrong_book.router)
app.include_router(settings.router)
app.include_router(quiz.router)
app.include_router(quiz_generator.router)
app.include_router(quiz_import.router)
app.include_router(quiz_session.router)
app.include_router(review.router)
app.include_router(stats.router)
app.include_router(logs.router)
app.include_router(tasks.router)
app.include_router(version.router)
app.include_router(ws.router)


@app.get("/admin", include_in_schema=False)
def admin_page():
    index = ADMIN_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("管理台尚未构建：在 admin 目录执行 npm run build", status_code=200)
    return FileResponse(index)


EXPERIMENTS_HTML = Path(__file__).resolve().parent / "static" / "experiments.html"


@app.get("/experiments", include_in_schema=False)
def experiments_page():
    """A/B 实验看板页面。"""
    if not EXPERIMENTS_HTML.exists():
        return HTMLResponse("实验看板页面不存在", status_code=404)
    return FileResponse(EXPERIMENTS_HTML)


if (ADMIN_DIR / "assets").exists():
    app.mount("/admin/assets", StaticFiles(directory=ADMIN_DIR / "assets"), name="admin-assets")


FAVICON_PATH = Path(__file__).resolve().parent / "static" / "favicon.ico"


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if FAVICON_PATH.exists():
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    return HTMLResponse("", status_code=204)


@app.get("/")
def health():
    return {"service": APP_NAME, "version": APP_VERSION, "status": "ok"}
