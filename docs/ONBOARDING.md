# ai学 项目入职指南（任意 Agent 快速上手）

> 生成日期：2026-08-23。给新加入项目的 Agent/贡献者：读完全文即可开始干活。
> 项目工作区：`C:\creategame\AI学`（后端/管理台/文档），Flutter App 在 `C:\ailearn\app`（中文路径会导致 Flutter 工具链崩溃，勿迁移）。

## 0. 项目概要

ai学 是一个**AI 驱动的互动式学习伴侣**：后端（FastAPI + SQLite）运行在局域网电脑，管理台（Vue3 Web）负责数据与 AI 配置，手机 App（Flutter）提供任务、课堂、知识库、我的四大界面。核心闭环：课程表 → 学习会话 → 课堂 AI 互动 → 做题判卷 → 掌握度 → 知识树 → 复习队列，全程 AI 参与且 token 节俭。

当前状态：**M0-M6 + 课堂 C1-C5 + 管理台 AI 能力（选区调整/自然语言生成）+ 课堂记忆容器 + 代码题沙箱判卷 全部完成**，桌面版与 Android 真机/模拟器可运行。见 `docs/PRD-v1.0.md`（产品决策冻结版）与 `docs/CLASSROOM-DESIGN-v1.0.md`（课堂设计）。

## 1. 架构总览

```
手机 App (Flutter, C:\ailearn\app)        管理台 (Vue3, C:\creategame\AI学\admin)
    │  REST / SSE / WebSocket                    │
    ▼                                           ▼
后端 FastAPI (C:\creategame\AI学\backend) ── SQLite (backend/data/ailearn.db)
    │  ├─ routers/   auth·course·session·chat·classroom·knowledge·quiz·review·stats·ai·ai_action·ws
    │  ├─ services/  scheduler·tutor·classroom·quiz·mastery·sediment·review·stats·ai_gateway·session_service
    │  └─ core/      config·db·security·ai_config·migrate
    │
    └─ LLM 网关（OpenAI 兼容，当前 opencode.ai/zen/go/v1，Key 存 DB 由管理台维护）
```

- 端口：后端 8000（`0.0.0.0`），管理台 `/admin`，SSE 流式 `/api/v1/classroom/interact`，WebSocket `/api/v1/ws`
- 后端启动：`backend\start-backend.bat`（双击）；管理台构建：`cd admin && npm run build`（产物自动进后端 static）
- APK 构建：`C:\ailearn\app\build-apk.ps1`（必须，内含 `FLUTTER_STORAGE_BASE_URL` 镜像环境变量）

## 2. 数据模型（15 表，`backend/app/models/`）

users · user_settings（含 ai.* 配置与 sprint_mode）· courses · schedule_items · schedule_exceptions · study_sessions · tasks · conversations（含 active_quiz_id/mainline_json 课堂状态）· messages（type: legacy/text/quiz/feedback）· sediment_suggestions · knowledge_nodes（多级树）· mastery_records · review_queue · quiz_questions · quiz_answers

约定：**时间统一 UTC 存储，状态机用本地时间驱动**；枚举集中在 `models/enums.py`；SQLite 加列用 `core/migrate.py` 的轻量迁移（启动自动执行）。

## 3. 关键原则（触碰前必读）

1. **后端是唯一事实源**：记忆/状态/判断全在后端，前端仅渲染输入（"前端零状态"）
2. **AI 交互 token 节俭**：只发选区/必要映射、字段白名单、AI 只输出 diff/动作 JSON（详见 `routers/ai_action.py`）；Prompt 全部短模板
3. **数据访问路径**：知识树掌握度由 `services/mastery.py` 驱动（父节点聚合、流水记录）；复习节奏 1/3/7 天
4. **AI 配置**：管理台「AI 设置」维护（自动保存、模型自动识别、主/视觉双模型），Key 只存 DB 不回显。请求必须带浏览器 User-Agent（否则 Cloudflare 403 1010）
5. **会话状态机**：scheduled→pre_class(课前15min)→in_class→review(课后30min)→done/overdue，由 `services/scheduler.py` 每分钟推进 + WS 广播

## 4. 常见陷阱

| 坑 | 说明 |
|---|---|
| Flutter 中文路径 | App 必须放 `C:\ailearn\app`，工作区中文路径会让 Dart 工具链崩溃 |
| APK 构建挂死 | 必须经 `build-apk.ps1`（FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn + 腾讯镜像仓库 + 超时配置） |
| Cloudflare 403 | 对网上模型端点请求要带浏览器 UA 头 |
| 端口 8000 冲突 | 后端占 8000；模型网关与 App 都指向 `http://192.168.3.4:8000` |
| `db.scalars(db.execute(...))` | 错误用法，应为 `db.scalars(select(...))` |

## 5. 当前优先事项（下一组任务候选）

1. ~~课堂记忆容器（course_memory）：课程间上下文继承~~ ✅ 已实现（`models/memory.py` + `services/course_memory.py`，集成到 classroom interact/activate/state）
2. ~~手机新版验证：App 连接检测版已装真机/模拟器，联调后端确认注册登录链路~~ ✅ 已验证（注册/登录/409 fallback/401 错误PIN 全部通过，MuMu 模拟器 APK 安装启动成功，opening 接口正常）
3. ~~AI 生成面板补丁：生成"映射外科目被忽略"时应返回提示~~ ✅ 已实现（后端 `ignored` 字段 + 前端警告展示）
4. ~~代码题沙箱判卷~~ ✅ 基础版已实现（`services/code_sandbox.py`：Python 沙箱执行 + 测试用例驱动判卷 + 超时/输出限制；C 语言需安装 gcc 自动启用；无测试用例时 fallback AI 评分）
5. 语音输入（后置）
6. M7（iOS 适配、多设备、多用户）— 预留

## 6. 常用命令速查

```powershell
# 后端
backend\start-backend.bat
# 管理台改完
cd C:\creategame\AI学\admin; npm run build
# App 改完（analyze + 构建 + 装模拟器）
cd C:\ailearn\app; flutter analyze
powershell -File C:\ailearn\app\build-apk.ps1
%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe -s 127.0.0.1:7555 install -r C:\ailearn\app\build\app\outputs\flutter-apk\app-debug.apk
# 冒烟脚本
python tools\verify_ai_action.py / verify_generate.py
```

## 7. 建议的首个任务

按"好奇心→小改动→大功能"推进：先读 `docs/PRD-v1.0.md` 与 `docs/CLASSROOM-DESIGN-v1.0.md` → 跑通后端启动与管理台 → 读 `routers/classroom.py` 与 `services/classroom.py`（最核心交互）→ 从清单第 3 条（生成提示补丁）练手。

## 8. 要问的问题

- 现在 AI Key 走哪个端点/模型？（管理台 AI 设置当前值）
- 最新的未完成交互是哪个？（课堂 C2 主线栈已启用、记忆容器未做）
- 手机端当前联调进度？（真机/模拟器装了什么版本）