# CLAUDE.md — ai学 项目入口（Agent 必读）

> 任何 agent 进入本项目，先读本文件，再读 `docs/ONBOARDING.md` 完整入职指南。
> ⚠️ **多 Agent 协作**：本工作区可能同时有 opencode 与 Doubao（豆包）操作。动文件前**必须先读根目录 `AGENTS.md` 和 `.agent-status.json`**，声明占用、避免冲突。

## 项目定位
AI 驱动的互动式学习伴侣（考研场景）。后端 FastAPI + SQLite 跑在电脑，管理台 Vue3，手机 App Flutter。
核心闭环：课程表 → 会话 → 课堂 AI 互动 → 判卷 → 掌握度 → 知识树 → 复习队列。

## 铁律（违反=事故）
1. **后端是唯一数据源**：记忆/状态/判断全在后端；前端只渲染与输入（零状态原则）
2. **Flutter App 必须留在 `C:\ailearn\app`**：中文路径会让 Dart 工具链崩溃；APK 构建必须走 `build-apk.ps1`
3. **AI 请求必须带浏览器 User-Agent**（否则 Cloudflare 403）；token 节俭：只发选区、字段白名单、AI 只回 diff
4. **Key 管理**：AI Key 只存 DB（user_settings），管理台维护，不回显不落代码

## 快速定位
- 后端入口：`backend/app/main.py`；课堂核心：`routers/classroom.py` + `services/classroom.py`
- 管理台：`admin/`（Vue3，build 产物进 `backend/app/static/admin`）
- 产品决策：`docs/PRD-v1.0.md`（冻结版）；课堂设计：`docs/CLASSROOM-DESIGN-v1.0.md`
- 当前进度与陷阱：`docs/ONBOARDING.md` §0 §4 §5（比本文件详细）

## 常用命令
```powershell
backend\start-backend.bat                    # 后端（端口 8000）
cd admin; npm run build                      # 管理台构建
powershell -File C:\ailearn\app\build-apk.ps1  # APK
adb -s 127.0.0.1:7555 install -r <apk>       # 装 MuMu 模拟器
```