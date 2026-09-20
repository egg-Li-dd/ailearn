@echo off
title AI学 - 一键启动
echo ========================================
echo    AI学 一键启动
echo ========================================
echo.

REM ---- 检测后端端口 8000 ----
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo [检测] 端口 8000 已被占用，跳过后端启动
    set BACKEND_STARTED=0
) else (
    echo [1/1] 启动后端服务...
    cd /d "C:\creategame\AI学\backend"
    set PUBLIC_BASE_URL=https://frp-egg.com:55450
    start "backend" /b ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    set BACKEND_STARTED=1
    echo       等待后端启动...
    timeout /t 4 /nobreak >nul
)

echo.
echo ========================================
echo    启动完成
echo ========================================
echo.
echo   管理台:    http://localhost:8000/admin
echo   后端地址:  http://127.0.0.1:8000
echo   API文档:   http://127.0.0.1:8000/docs
echo   公网地址:  https://frp-egg.com:55450/admin
echo.
echo   管理台账号: admin / ailearn2026
echo.
echo   关闭本窗口将同时停止后端服务
echo.

REM ---- 自动打开管理台 ----
start http://localhost:8000/admin

pause
