"""ai学 后端配置。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 全局库（用户表、AI通道、系统日志等共享资源）
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATA_DIR / 'ailearn.db'}"

# 用户业务库目录（物理分库：每个用户一个 .db 文件）
USER_DB_DIR = DATA_DIR / "users"
USER_DB_DIR.mkdir(parents=True, exist_ok=True)

APP_NAME = "ai学"
APP_VERSION = "0.1.0"

# App 客户端版本检查（自托管场景，由部署者维护最新版本号与下载地址）
APP_LATEST_VERSION = os.getenv("AILEARN_APP_LATEST_VERSION", "1.0.0")
APP_DOWNLOAD_URL = os.getenv("AILEARN_APP_DOWNLOAD_URL", "")
APP_MIN_COMPATIBLE = os.getenv("AILEARN_APP_MIN_COMPATIBLE", "1.0.0")
APP_RELEASE_NOTES = os.getenv("AILEARN_APP_RELEASE_NOTES", "")

# PIN 加密参数
PIN_ITERATIONS = 100_000

# CORS：局域网阶段默认全开，可通过环境变量收紧
CORS_ORIGINS = os.getenv("AILEARN_CORS_ORIGINS", "*")
if CORS_ORIGINS == "*":
    CORS_ORIGINS_LIST = ["*"]
else:
    CORS_ORIGINS_LIST = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]

# 服务监听
HOST = os.getenv("AILEARN_HOST", "0.0.0.0")
PORT = int(os.getenv("AILEARN_PORT", "8000"))

# 调试模式
DEBUG = os.getenv("AILEARN_DEBUG", "").lower() in ("1", "true", "yes")
