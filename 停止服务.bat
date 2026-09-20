@echo off
echo 停止后端服务（端口8000）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo 终止进程 %%a
    taskkill /F /PID %%a
)
echo 停止管理台（端口5173）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    echo 终止进程 %%a
    taskkill /F /PID %%a
)
echo 完成
pause