@echo off
echo ========================================
echo   ai学 构建管理台前端
echo ========================================
echo.

cd /d "%~dp0"

if not exist "node_modules" (
    echo [信息] 安装依赖...
    call npm install
)

echo [信息] 构建中...
call npm run build

if errorlevel 1 (
    echo [错误] 构建失败
    pause
    exit /b 1
)

echo.
echo [完成] 构建产物已输出到 backend\app\static\admin\
echo [信息] 启动后端后访问 http://localhost:8000/admin
echo.
pause
