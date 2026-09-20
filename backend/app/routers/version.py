"""版本检查路由。

App 启动时调用，比较本地版本与服务端配置的最新版本，
有新版本时返回下载地址与更新说明。
"""
from fastapi import APIRouter

from ..core.config import (
    APP_DOWNLOAD_URL,
    APP_LATEST_VERSION,
    APP_MIN_COMPATIBLE,
    APP_RELEASE_NOTES,
    APP_VERSION,
)

router = APIRouter(prefix="/api/v1/version", tags=["version"])


@router.get("")
def get_version() -> dict:
    """返回服务端版本信息与 App 最新版本。

    - ``backend_version``: 后端服务版本
    - ``latest_version``:  App 最新可用版本（部署者配置）
    - ``min_compatible``:  App 最低兼容版本（低于此值建议强制更新）
    - ``download_url``:    APK 下载地址（为空表示未配置下载）
    - ``release_notes``:   更新说明
    """
    return {
        "backend_version": APP_VERSION,
        "latest_version": APP_LATEST_VERSION,
        "min_compatible": APP_MIN_COMPATIBLE,
        "download_url": APP_DOWNLOAD_URL,
        "release_notes": APP_RELEASE_NOTES,
    }
