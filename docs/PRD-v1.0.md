# ai学 产品规划文档 v1.0（决策定稿）

> AI 驱动的互动式学习伴侣。第一用户：eggLi（计算机考研备考）。
> 本版本为决策冻结版：所有设计点均已给定明确决定与理由，不再留开放问题。
> 文档变更需走"决策修订"流程（修改 + 理由记录）。

---

## 0. 决策总表（DECISIONS）

| # | 决策域 | 决定 | 理由 |
|---|---|---|---|
| D01 | 用户模型 | 单用户优先，锁 PIN；users 表与 JWT 字段预留 | 首个深度用户是本人；多用户后置 |
| D02 | 科目预置 | 预置 7 科目模板：408 四科（数据结构/组成原理/操作系统/计算机网络）、数学一、英语一、政治 | 贴合考研场景，可增删 |
| D03 | 课程表录入 | 管理台手动录入为主；支持"粘贴网课课表文本 → AI 解析成结构" | 手动最稳，AI 解析省力 |
| D04 | 课表模型 | 周模板 + 日期例外 + 单次补课；冲突管理台告警 | 覆盖常规课表 + 调课场景 |
| D05 | 会话状态机 | SCHEDULED→PRE_CLASS(课前15min)→IN_CLASS→REVIEW(课后30min)→DONE/OVERDUE | 课前/课中/课后三段驱动 |
| D06 | 任务生成 | 规划 Agent 课前 15 分钟生成；失败用科目模板兜底；管理台可人工调整 | AI 定制 + 兜底可靠 |
| D07 | 答疑模式 | 三种：自由问（默认）/ 做题 / 小测 | 覆盖问答、练习、诊断 |
| D08 | 知识点标注 | AI 回答内软标注（点击可跳知识树）；不自动改掌握度；沉淀需用户确认 | 防止 AI 误判污染数据 |
| D09 | 知识沉淀 | 每轮问答结束 AI 生成沉淀建议卡，用户确认后写入知识树（来源=答疑沉淀） | 对话变资产的入口 |
| D10 | 复习节奏 | 沉淀知识点进入复习队列：第 1/3/7 天各出 1 题（参数可配） | 艾宾浩斯节奏 |
| D11 | 掌握度模型 | 0-100；四类事件驱动：做题(AI评/对错)、AI判定(0.7/0.3加权)、复习(权重1.5x)、自评；难度校准 | 规则+AI 混合，防刷分 |
| D12 | 掌握状态 | <40 未学 / 40-69 学习中 / 70-84 已掌握 / 到期未复习→待复习 | 阈值简单可解释 |
| D13 | 出题策略 | 难度随掌握度自适应；题型映射：选择(<50)/填空(50-70)/简答代码(>70)；题目入库可复用 | 循序渐进，题库复用 |
| D14 | 知识树结构 | 科目根→章节(多级)→知识点(可再挂子点)；支持"粘贴考纲文本→AI生成骨架" | 大纲驱动，快速建树 |
| D15 | AI 教练人格 | 默认"认真、直接、有判断力的教练型"，可自定义名称/语气 | 符合用户期望的顾问感 |
| D16 | 数据导出 | Markdown 笔记（知识树按科目导出）+ JSON 全量备份 | 数据永不锁死 |
| D17 | 离线能力 | App 缓存任务与知识树视图；答疑需联网；本地 AlarmManager 兜底提醒 | WS 断连也能响铃 |
| D18 | 认证 | 设备注册 + 4-6 位 PIN；token 存设备；预留 JWT 多用户 | 局域网够用，可升级 |
| D19 | 技术栈 | Flutter + FastAPI + SQLite + APScheduler + WebSocket/SSE + Vue3 管理台 | 前轮选型定稿 |
| D20 | 部署 | uvicorn 常驻端口 8000，开机自启；管理台 http://局域网IP:8000/admin；App 设置页配后端地址 | 单机零运维 |
| D21 | 额外功能 | 考研冲刺模式（倒计时强化任务）；周报（AI 每周自动生成学习总结）；语音输入（延后期） | 差异化与长期钩子 |

---

## 1. 产品定位与核心闭环（同 v0.2，冻结）

AI 教练 + 个人学习闭环。数据飞轮：
```
课程表 → 规划Agent生成任务清单 → 任务界面按时间流转(课前/课中/课后)
   ↑                                                      ↓
掌握度更新 ← 答题结果/AI判定 ← 出题Agent生成巩固题 ← 答疑互动(带RAG)
   ↓
知识树生长 → 薄弱节点 → 影响下一轮任务生成和出题难度 ←
```

## 2. 学习会话与任务引擎（D05/D06）

### 状态机（定稿）
```
SCHEDULED → PRE_CLASS(课前15min触发) → IN_CLASS(上课时间) → REVIEW(课后30min) → DONE
                                                              ↘ OVERDUE(未完成)
```
- 迁移由后端 APScheduler 每分钟扫描 schedule 驱动
- OVERDUE 会话：进入复习队列候选，不阻塞新会话
- 调课/补课：修改 schedule 后重新生成目标会话；已有互动数据的会话保留原数据

### 任务清单
- 结构：会话 → 任务卡片序列。卡片：类型(阅读/练习/记忆/思考/复习)、标题、目标知识点引用、预计时长、状态(未开始/进行中/完成/跳过)、顺序
- 生成（规划 Agent）输入：科目、本课主题、该科目掌握度最低 N=5 个节点、复习队列到期项
- 输出：3-8 张卡片（JSON Schema 约束）
- 兜底：LLM 失败 → 按科目默认任务模板（管理台可维护）
- 课中全屏：顶部本课目标（1-3 条，AI 从课程大纲生成），中部任务卡片流，卡片可一键"问 AI"

## 3. 答疑互动（D07/D08/D09/D10）

### 三模式
| 模式 | 触发 | 行为 |
|---|---|---|
| 自由问 | 默认 | 流式回答 + RAG + 软知识点标注 |
| 做题 | 用户选"做题"或点卡片里的问AI | 按知识点+难度出题（见出题策略），作答后 AI 判定 |
| 小测 | 用户选"小测"或课后自动建议 | 5 题快测，结束输出掌握度诊断 |

### 知识点标注（软标注）
- AI 回答中以"知识点"样式标注提及的概念，点击跳到知识树对应节点
- 软标注不写掌握度；只有沉淀建议被确认后才落库

### 沉淀建议
- 每轮问答结束，AI 生成 1-5 条建议卡：`[新概念]xxx` / `[纠错]xxx` / `[结论]xxx`
- 用户一键全收或逐条确认 → 写入 knowledge_nodes（来源=答疑沉淀，难度由 AI 建议用户可改）→ 进入复习队列（第 1/3/7 天）
- 已存在同名节点：合并为"补充内容"挂在节点上，不新建

### RAG
- 检索范围：知识库同科目节点 + 全局关键词；命中不足时允许纯 LLM 回答
- 回答引用：展示来源节点名（软链接）

## 4. 知识库（D11/D12/D14）

### 树结构
- 科目根（7 个预置）→ 章节（多级）→ 知识点（可再挂子节点）
- 建树方式：
  1. 管理台"从考纲生成骨架"：粘贴考纲/目录文本 → AI 解析成树（推荐首建）
  2. 手动单点添加
  3. 答疑沉淀自动添加（D09）

### 节点属性（定稿）
| 字段 | 类型 | 说明 |
|---|---|---|
| id/parent_id | | 树关系，支持多级 |
| subject_id | | 科目 |
| name | str | 节点名 |
| level | 1-5 | 层级（科目/章/节/知识点/子知识点） |
| difficulty | 1-5 | 难度 |
| mastery | 0-100 | 掌握度（叶子节点为主，父节点=子节点加权均值） |
| status | enum | 未学/学习中/已掌握/待复习 |
| source | enum | manual/qa_sediment/ai_generated/paste |
| summary | str(opt) | AI 生成的内容概览（可空） |
| quiz_ids | [str] | 关联题目 |
| created/updated | ts | |

### 前端视图
- 树状浏览（折叠展开）、按科目切换、按掌握度/难度过滤、热力着色（<40 深红、40-69 橙、70-84 青、≥85 绿）
- 全局搜索（名称 + summary 全文）

## 5. 掌握度模型（D11/D12，定稿算法）

### 事件与影响
| 事件 | 影响 | 备注 |
|---|---|---|
| 选择/判断正确 | +5（连续正确 +2/题，封顶 +15） | 规则 |
| 选择/判断错误 | -10 | 规则 |
| 简答/代码题 | AI 评分 s∈[0,100]，Δ = (s-50)/10，取整 | AI 判定 |
| 复习队列题目 | 上项 × 1.5 | 复习权重 |
| 小测 AI 诊断 | 与规则加权 0.7 规则 / 0.3 AI | AI 判定置信度<0.6 时忽略 AI 部分 |
| 用户自评 | 手动设"已掌握"→85；"不熟"→-15 | 手动 |

### 难度校准
- 单次影响 × (1 - 0.15×(difficulty-3))：难题控涨速，防止简单题刷满
- 更新后重算父节点加权均值（权重 = 子节点数）

### 状态阈值
- 未学：mastery=0 或从未接触
- 学习中：1-69
- 已掌握：70-84
- 待复习：曾≥70 且 7 天未复习（review_queue 驱动）
- 已掌握且 ≥85：复习间隔拉长到 14 天

## 6. 出题与复习队列（D10/D13）

### 出题策略
- 输入：知识点 + 当前掌握度
- 难度与题型：掌握度<50 → 基础/选择；50-70 → 中等/填空；>70 → 综合/简答或代码
- 出题数量：做题模式 1-3 题连续；小测 5 题；复习 1 题
- 题目 JSON Schema：题干、选项(可选)、答案、解析、知识点引用、难度、题型
- 题库持久化：quiz_questions；复习优先复用旧题（间隔>7 天），否则新出
- 作答判定：选择/填空规则判；简答/代码 AI 判 + 给解析

### 复习队列
- 入队：沉淀确认（1/3/7 天）、OVERDUE 会话知识点
- 到期：推送提醒 + 出 1 题；作答后更新掌握度（1.5x 权重）
- 队列页：今日待复习数量、列表、一键开始

## 7. 我的界面（D15/D16/D21）

- 教练卡片：默认名"教练"（可改），人格设定（语气/严格度/鼓励频率），显示一句话每日寄语（AI 生成，按当日任务+状态）
- 数据：连续学习天数、本周学时、7 科掌握度雷达图、复习队列数、学习热力图
- 冲刺模式开关：开启后任务密度 ×1.5、出题频率翻倍、显示考研倒计时
- 周报：每周日 21:00 AI 生成学习周报（掌握度变化、薄弱点、下周建议）
- 设置：模型选择与 API Key（DeepSeek/千问/豆包，OpenAI 兼容）、人格、复习节奏参数、后端地址、导出（Markdown/JSON）

## 8. 管理台（/admin）

- 课程表管理：周模板 CRUD、例外日期、补课、冲突告警
- 知识树管理：全量 CRUD、考纲粘贴建树、批量导入
- 任务配置：科目默认任务模板、规划参数（薄弱点 N、卡片数范围）
- AI 设置：模型路由（每角色独立配置）、温度、用量统计
- 数据浏览：会话记录、掌握度流水、沉淀建议历史

## 9. 数据模型（字段级，v1.0）

users(id, device_id, pin_hash, created_at)
courses(id, name, subject_code, color, sort)
schedule_items(id, course_id, weekday, start_time, end_time, location, is_active)
schedule_exceptions(id, date, course_id(optional), action[add/remove], start_time, end_time)
study_sessions(id, schedule_item_id, course_id, date, status, started_at, finished_at)
tasks(id, session_id, seq, type, title, target_knowledge_id, est_minutes, status)
conversations(id, session_id(optional), mode, started_at, ended_at)
messages(id, conversation_id, role, content, ref_knowledge_ids, created_at)
sediment_suggestions(id, conversation_id, kind[concept/correction/conclusion], content, status[pending/accepted/rejected])
knowledge_nodes(id, parent_id, subject_id, name, level, difficulty, mastery, status, source, summary, quiz_ids, created_at, updated_at)
mastery_records(id, node_id, old_value, new_value, reason, source, created_at)
quiz_questions(id, node_id, difficulty, qtype, payload_json, created_at)
quiz_answers(id, question_id, user_answer, score, ai_feedback, created_at)
review_queue(id, node_id, due_at, status[open/done], source, created_at)
user_settings(key, value)

## 10. API 清单（v1.0）

- POST /api/v1/auth/register · login
- CRUD /api/v1/courses · /api/v1/schedule · /api/v1/schedule/exceptions
- GET /api/v1/sessions/today · GET /api/v1/sessions/{id} · GET /api/v1/tasks?session_id=
- POST /api/v1/conversations · GET /api/v1/conversations/{id}/messages（SSE 流式）· POST /api/v1/messages
- POST /api/v1/quiz/generate · POST /api/v1/quiz/answer
- GET /api/v1/knowledge/tree?subject= · POST /api/v1/knowledge · PUT/DELETE /api/v1/knowledge/{id}
- POST /api/v1/knowledge/import-outline（考纲粘贴建树）
- POST /api/v1/sediments/{id}/accept · reject
- GET /api/v1/review/today · POST /api/v1/review/{id}/complete
- GET /api/v1/user/profile · PATCH /api/v1/user/settings · GET /api/v1/user/export/{format}
- GET /api/v1/stats/weekly · radar
- WS /ws（任务事件推送：PRE_CLASS/IN_CLASS/REVIEW 迁移、复习到期提醒）

## 11. 仓库结构（定稿）

```
ai学/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/ (config, db, security)
│  │  ├─ models/ (SQLAlchemy)
│  │  ├─ schemas/ (Pydantic)
│  │  ├─ routers/ (v1 + admin)
│  │  ├─ services/
│  │  │  ├─ ai_gateway.py (OpenAI 兼容网关 + 用量)
│  │  │  ├─ planner.py (规划 Agent)
│  │  │  ├─ tutor.py (答疑 Agent + RAG)
│  │  │  ├─ quiz.py (出题/判定 Agent)
│  │  │  ├─ mastery.py (掌握度裁判)
│  │  │  └─ scheduler.py (APScheduler 状态机)
│  │  └─ static/admin/ (Vue3 SPA 构建产物)
│  └─ pyproject.toml
├─ admin/ (Vue3 源码，dev 态，构建进 backend/static)
├─ app/ (Flutter)
│  └─ lib/features/{tasks, chat, knowledge, profile, core}
└─ docs/
```

## 12. 部署（D20）

- 后端：uvicorn 服务，端口 8000，注册 Windows 开机自启（任务计划或 nssm）
- 管理台：http://<电脑局域网IP>:8000/admin
- App：设置页填后端地址（默认 http://192.168.1.100:8000，可在管理台提示实际 IP）
- 数据安全：局域网不暴露公网；备份 = 定期复制 SQLite 文件

## 13. 里程碑（定稿）

| 阶段 | 内容 | 验收 |
|---|---|---|
| M0 | 建库 + 全部数据模型 + 认证 PIN | migrate 通过，register/login 通 |
| M1 | 课程表/例外 CRUD + 管理台骨架 + App 四 Tab 壳 + 登录 | 管理台可维护课表，App 双端连通 |
| M2 | 调度器 + 会话状态机 + WS 推送 + 课中全屏任务流 | 时间到 App 自动切课中模式 |
| M3 | AI 网关 + 自由问流式 + RAG + 软标注 | 打字机效果 + 知识点跳转 |
| M4 | 知识树全链路（管理台建树/考纲导入 + 前端树视图 + 掌握度更新） | 做题后树热力变化可见 |
| M5 | 出题闭环 + 沉淀 + 复习队列 | 完整飞轮转起来 |
| M6 | 我的界面 + 周报 + 冲刺模式 + 导出 | 打磨发布 |
| M7 | iOS 适配、多设备、多用户（后置） | 预留 |

## 14. 风险与对策

- LLM 输出不稳定（任务清单/题目/判定）：全部 JSON Schema 约束 + 失败重试 + 模板兜底
- 掌握度被 AI 误判污染：软标注机制 + 沉淀需确认 + 流水可回溯（mastery_records）
- WebSocket 断连导致任务错过：本地 AlarmManager 兜底 + 下次打开 App 拉全量
- 单机故障：SQLite 定期备份，文档写明恢复步骤