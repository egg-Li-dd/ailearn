@echo off
title 提示词优化方案 - 演示页面
echo 启动本地服务器...
echo 演示地址: http://localhost:8765
echo.
start http://localhost:8765
python -m http.server 8765
pause