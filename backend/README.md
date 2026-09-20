# ai学 后端

AI 驱动的个性化学习平台后端，基于 FastAPI + SQLAlchemy + SQLite。

## 快速开始

### 1. 环境要求

- Python 3.11+
- （可选）Node.js 18+（构建管理台前端）

### 2. 安装与启动

**Windows 一键启动：**
```powershell
cd backend
.\start-backend.bat
```

**手动启动：**
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Docker 启动：**
```bash
docker-compose up -d
```

### 3. 访问地址

- 服务根路径：`http://localhost:8000/`
- API 文档（Swagger）：`http://localhost:8000/docs`
- 管理台：`http://localhost:8000/admin`（需先构建前端）

### 4. 构建管理台前端

```bash
cd admin
.\build-admin.bat  # Windows
# 或手动：npm install && npm run build
```

构建产物自动输出到 `backend/app/static/admin/`。

## 项目架构

```
backend/
├── app/
│   ├── main.py              # 应用入口（生命周期、路由注册、中间件）
│   ├── core/                # 核心基础设施
│   │   ├── config.py        # 配置（环境变量驱动）
│   │   ├── db.py            # 数据库引擎 + WAL 模式 + 会话管理
│   │   ├── security.py      # PIN 哈希 + Token 生成
│   │   ├── ai_config.py     # AI 网关配置（密钥不回显）
│   │   ├── exceptions.py    # 全局异常处理
│   │   ├── logging_config.py # 日志配置（控制台+文件轮转）
│   │   ├── migrate.py       # 轻量迁移（SQLite 加列）
│   │   └── utils.py         # 通用工具
│   ├── models/              # SQLAlchemy 模型（15 张表）
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── routers/             # API 路由
│   ├── services/            # 业务逻辑层
│   └── static/admin/        # 前端构建产物
├── data/
│   ├── ailearn.db           # SQLite 数据库
│   ├── ai_config.json       # AI 配置（可选，数据库优先）
│   ├── backups/             # 数据库备份
│   └── logs/                # 日志文件
├── tools/
│   └── backup_db.py         # 数据库备份/恢复工具
├── requirements.txt
├── Dockerfile
├── .env.example
├── start-backend.bat
└── start-backend.ps1
```

## 功能模块

| 模块 | 说明 | 路由前缀 |
|---|---|---|
| 认证 | 设备注册 + PIN 登录 + Token 鉴权 | `/api/v1/auth` |
| 课程管理 | 科目 CRUD + 周课表 + 日期例外 + 冲突检测 | `/api/v1/courses`, `/api/v1/schedule` |
| 学习会话 | 会话生成 + 状态机 + 任务卡 + 规划 Agent | `/api/v1/sessions` |
| AI 网关 | OpenAI 兼容接口 + 流式 + 自动重试 + 配置管理 | `/api/v1/ai` |
| 知识树 | 树形 CRUD + 考纲粘贴建树 + 掌握度聚合 | `/api/v1/knowledge` |
| 出题判卷 | AI 出题 + 客观/主观题判卷 + 掌握度联动 | `/api/v1/quiz` |
| 课堂引擎 | 块协议 + 意图判别 + 主线栈 + 小测批 | `/api/v1/classroom` |
| 答疑 | SSE 流式 + RAG 检索 + 软标注 + 知识沉淀 | `/api/v1/conversations` |
| 复习队列 | 艾宾浩斯节奏 + 到期提醒 + 复习作答 | `/api/v1/review` |
| 统计看板 | 总览 + 雷达图 + 热力图 + 周报 | `/api/v1/stats` |
| 语音识别 | ASR 音频转文字（funasr，可选） | `/api/v1/asr` |
| WebSocket | 实时状态推送 | `/api/v1/ws` |

## 配置项

通过环境变量配置（参考 `.env.example`）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AILEARN_HOST` | `0.0.0.0` | 监听地址 |
| `AILEARN_PORT` | `8000` | 监听端口 |
| `AILEARN_DEBUG` | `false` | 调试模式 |
| `AILEARN_CORS_ORIGINS` | `*` | CORS 允许来源，逗号分隔 |

AI 配置在管理台「AI 设置」页面配置，存储于数据库，密钥永不回显。

## 数据库

- 引擎：SQLite（WAL 模式，支持并发读）
- 位置：`backend/data/ailearn.db`
- 建表：启动时自动 `create_all`
- 迁移：轻量迁移（`core/migrate.py`）处理加列
- 备份：`python tools/backup_db.py`（保留最近 20 份）

## 常用工具

```bash
# 备份数据库
python tools/backup_db.py

# 列出所有备份
python tools/backup_db.py --list

# 从备份恢复
python tools/backup_db.py --restore ailearn_20260823-120000.db

# 保留最近 10 份备份
python tools/backup_db.py --keep 10
```

## 开发约定

- 时间统一 UTC 存储，展示层转本地（东八区）
- 枚举值集中在 `app/models/enums.py`
- API 统一前缀 `/api/v1`
- 错误响应统一格式：`{"detail": "错误信息"}`
- AI 调用内置重试（429/5xx 最多 2 次，指数退避）
- 日志输出到控制台 + `data/logs/ailearn.log`（按天轮转，保留 14 天）
