@echo off
title AI学 - 后端服务
echo 启动后端服务...
cd /d "C:\creategame\AI学\backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause