# ai学 — AI 驱动的个性化学习平台

> 面向考研等自主学习场景的 AI 学习教练平台，支持课表管理、知识树、AI 出题判卷、课堂引擎、答疑沉淀、复习队列等全链路功能。

## 项目结构

```
AI学/
├── admin/              # 管理台前端（Vue 3 + Vite）
├── backend/            # 后端服务（FastAPI + SQLAlchemy + SQLite）
├── docs/               # 产品文档（PRD、UI 规范、课堂设计等）
├── prototype/          # 前端原型（HTML 静态页面）
├── tools/              # 工具脚本（备份、诊断、验证等）
├── docker-compose.yml  # Docker 一键部署
└── .gitignore
```

## 快速开始

### 方式一：一键启动（推荐）

```bash
# 1. 启动后端
cd backend
.\start-backend.bat

# 2. 另开终端，启动前端开发服务器（可选，开发时用）
cd admin
.\start-admin.bat
```

### 方式二：Docker 部署

```bash
docker-compose up -d
```

### 访问地址

| 服务 | 地址 |
|---|---|
| 后端 API | http://localhost:8000/ |
| API 文档 | http://localhost:8000/docs |
| 管理台 | http://localhost:8000/admin |
| 前端开发服务器 | http://localhost:5173 |

## 核心功能

- **课程管理**：科目、周课表、日期例外，自动时间冲突检测
- **学习会话**：基于课表自动生成会话，状态机驱动（课前/课中/复习/完成）
- **规划 Agent**：AI 自动生成课前任务清单，LLM 失败自动模板兜底
- **知识树**：树形结构管理知识点，掌握度自动聚合，支持考纲粘贴建树
- **AI 出题判卷**：按掌握度自适应选题型（选择/填空/简答/代码），AI 评分
- **课堂引擎**：块协议 + 意图判别 + 主线栈 + 小测批，前端零状态
- **答疑系统**：SSE 流式 + RAG 检索 + 软标注，对话可沉淀为知识点
- **复习队列**：艾宾浩斯遗忘曲线，自动安排复习节奏
- **统计看板**：连续学习天数、科目掌握度雷达、学习热力图、AI 周报
- **AI 网关**：OpenAI 兼容接口，支持多模型，自动重试，密钥安全存储

## 技术栈

**后端：**
- FastAPI 0.141+（异步 Web 框架）
- SQLAlchemy 2.0+（ORM）
- SQLite（WAL 模式）
- httpx（HTTP 客户端，AI 网关）
- APScheduler（任务调度）

**前端：**
- Vue 3.4+（组合式 API）
- Vite 5+（构建工具）
- 原生 CSS（设计令牌体系，无 UI 框架依赖）

## 文档

- [PRD v1.0](docs/PRD-v1.0.md) — 产品需求文档
- [UI 规范 v1.0](docs/UI-SPEC-v1.0.md) — 视觉设计规范
- [课堂设计 v1.0](docs/CLASSROOM-DESIGN-v1.0.md) — 课堂引擎设计
- [新手指南](docs/ONBOARDING.md) — 上手指南
- [后端 README](backend/README.md) — 后端详细文档

## 数据安全

- PIN 密码使用 PBKDF2-HMAC-SHA256 加盐哈希存储
- API Key 仅存储于本地数据库，任何接口不回显明文
- 数据库备份工具支持自动备份与一键恢复
- 支持配置 CORS 来源限制，公网部署前请收紧

## 许可证

私有项目，未经授权不得商用。
