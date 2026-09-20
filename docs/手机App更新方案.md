# 手机 App 更新方案

> 项目：ai学 App（Flutter）
> 位置：`C:\ailearn\app`
> 技术栈：Flutter 3.x + Material 3，原生 setState（无状态管理库、无路由库）
> 最后更新：2026-08-25
> 关联文档：[前端重构方案.md](前端重构方案.md)（管理台）、[后端更新方案.md](后端更新方案.md)、[UI-SPEC-v1.0.md](UI-SPEC-v1.0.md)

---

## 目录

- [一、现状分析](#一现状分析)
- [二、整体设计方向](#二整体设计方向)
- [三、通用组件开发](#三通用组件开发)
- [四、页面重构](#四页面重构)
  - [4.1 登录页](#41-登录页)
  - [4.2 任务页](#42-任务页)
  - [4.3 课堂页](#43-课堂页)
  - [4.4 知识库页](#44-知识库页)
  - [4.5 答疑聊天页](#45-答疑聊天页)
  - [4.6 复习队列页](#46-复习队列页)
  - [4.7 手写板测验页](#47-手写板测验页)
  - [4.8 我的页](#48-我的页)
- [五、全局功能](#五全局功能)
- [六、Flutter 设计规范](#六flutter-设计规范)
- [七、文件结构](#七文件结构)
- [八、实施计划](#八实施计划)
- [九、借鉴开源项目汇总](#九借鉴开源项目汇总)
- [十、关键决策记录](#十关键决策记录)

---

## 一、现状分析

### 1.1 现有页面清单

| 界面 | 文件 | 行数 | 状态 |
|------|------|------|------|
| 主壳（底部四 Tab） | `lib/features/shell/home_shell.dart` | 83 | 完成 |
| 登录 | `lib/features/login/login_page.dart` | 156 | 可用，粗糙 |
| 任务 | `lib/features/tasks/tasks_page.dart` + `task_widgets.dart` | 366+ | 完成 |
| 课堂 | `lib/features/classroom/classroom_page.dart` | **1486** | 功能全，**单文件过大** |
| 知识库 | `lib/features/knowledge/knowledge_page.dart` | 374 | 完成（无限层级+热力着色） |
| 答疑 | `lib/features/chat/chat_page.dart` | 542 | 完成 |
| 手写板 | `lib/features/handwrite/handwrite_board.dart` + `handwrite_quiz_page.dart` | 342+ | 完成 |
| 复习队列 | `lib/features/review/review_page.dart` | 164 | 可用，**交互朴素** |
| 我的 | `lib/features/profile/profile_page.dart` | 694 | 功能全，**单文件较大** |
| 主题/API/WS | `lib/core/*` | — | 完成 |

### 1.2 核心问题

| 问题 | 说明 |
|------|------|
| **课堂/我的单文件过大** | `classroom_page.dart` 1486 行、`profile_page.dart` 694 行，块渲染、题目卡、判卷流全部塞在一个 State 里，无法复用、难以测试 |
| **复习算法是固定 1/3/7 天** | 后端写死艾宾浩斯间隔，未按真实作答难度/遗忘率动态调整（`review_page.dart` 仅"对/错"两档） |
| **手写识别依赖后端大模型** | 手写板导出 PNG 上传，后端 LLM 看图识别：慢（秒级）、耗 token、离线不可用 |
| **无深色模式** | `theme.dart` 只有 `AppTheme.light`；UI-SPEC 2.3 已定义深色 Token（#14151A 等）但未实现 |
| **无本地缓存** | 任务/知识树/答疑历史全部每次实时拉取，弱网/后端不可用时白屏；仅 `shared_preferences` 存 token/会话 ID |
| **无到期/课前提醒** | 复习队列、课中状态变化全靠用户主动打开；管理台已有课表但 App 无推送 |
| **聊天只渲纯文本** | SSE 流式内容不做 Markdown/代码块/公式渲染，长答案可读性差；无引用来源展示 |
| **登录页无持久化体验** | 每次手输设备号+PIN；无"记住设备号/指纹解锁" |
| **知识树无拖拽/富交互** | 管理台已支持的拖拽、详情面板、掌握度历史，App 端只有静态树+搜索 |

### 1.3 与后端/管理台的关系

- 后端「后端更新方案.md」已新增：scheduling 复习策略相关准备（教师/教室字段、掌握度流水 `mastery_records`、审计日志表）。
- 管理台「前端重构方案.md」已落地：科目卡片、周课表网格、日期例外日历、知识树（无限层级+思维导图）、AI 生成。
- **App 端无需重建业务链路（课堂块协议、SSE、WS、状态机都是好的），本次是体验增强 + 复用性重构**。

---

## 二、整体设计方向

### 2.1 设计原则（对齐 UI-SPEC v1.0）

- 一切改动遵循既有 **AppColors / AppTheme** 令牌，不做第二代配色
- **延续"纸感 + AI 辅助色"**：浅色底 `#F6F6F2`，AI 元素用 `ai (#8A5CD6)`；克制动画 ≤300ms
- **小步重构**：不引状态管理库、不引路由库，保持 `setState` + `ValueNotifier`（风险最小）
- **能离线则离线**：本机可算的先在本地算（手写识别、FSRS 排程预览、缓存最近数据）
- **与管理台信息同构**：科目色 `#3E63DD/#8A5CD6/#3E8E58/#C77E1E/#C24238` 全端一致

### 2.2 主题升级

- 新增 `AppTheme.dark`：映射 UI-SPEC 2.3 深色 Token（bg `#14151A`、card `#1D1F26`、primary `#6E8FF0`、ai `#A583E8` 等）
- `MaterialApp` 增加 `darkTheme`，跟随系统，后续在"我的-设置"加手动开关（默认跟随系统）
- 底部 Tab/卡片/输入框/进度条全部用 `Theme.of(context)` 取色，替换硬编码 `AppColors.*` 引用（保留 `AppColors` 作为浅色字面量常量，深色走 `ColorScheme`）

### 2.3 页面通用节构

```
┌──────────────────────────────┐
│ 标题（AppBar）   [刷新]      │
├──────────────────────────────┤
│ 统计/状态卡片（2-3 个，横向）  │
├──────────────────────────────┤
│ 搜索/筛选栏（可选）           │
├──────────────────────────────┤
│ 内容区：卡片列表/网格/流       │
├──────────────────────────────┤
│ 空状态：图标+文案+引导按钮     │
└──────────────────────────────┘
```

---

## 三、通用组件开发

> 优先级：P0。放在 `lib/widgets/`（新增目录），对齐管理台 `components/` 体系。

| 组件 | 文件 | 说明 | 借鉴参考 |
|------|------|------|----------|
| **SectionCard** | `widgets/section_card.dart` | 白卡容器（圆角 12 / 边框 0.5 / 阴影微），统一替代手写 Container | StudyRAG glass card |
| **StatPill** | `widgets/stat_pill.dart` | 图标+数字+副标题的小统计条（任务页"3 节课/5 待复习/2 已打卡"） | 管理台 StatCard 的移动版 |
| **EmptyView** | `widgets/empty_view.dart` | 空状态：图标+标题+副文案+按钮（对齐管理台 EmptyState 文案风格） | — |
| **ErrorView** | `widgets/error_view.dart` | 错误态：错误信息+重试按钮（统一现有 7 处重复的"出错-重试"代码） | — |
| **MasteryBadge** | `widgets/mastery_badge.dart` | 掌握度色标/进度环（复用 `masteryColor()`，供知识树/题目卡/我的复用） | engram 节点着色 |
| **CoursePill** | `widgets/course_pill.dart` | 科目色 pill（配色+名称，知识库 chips、任务卡科目条、雷达图图例共用） | — |
| **StreamingText** | `widgets/streaming_text.dart` | 流式文本增量渲染（课堂/答疑共用，支持打字光标、流式结束后转 Markdown） | ai-study-companion flutter_chat_ui |
| **MarkdownView** | `widgets/markdown_view.dart` | Markdown/代码块/行内公式渲染（答疑 & 课堂 AI 文本） | flutter_markdown |
| **SheetPage** | `widgets/sheet_page.dart` | 底部抽屉页（复习作答、题目详情等轻交互，替代导航） | GemMate sheet |
| **AnswerButtons** | `widgets/answer_buttons.dart` | 复习记忆档位按钮（重做/模糊/记得/清楚，带预估间隔） | Anki 四档二态演进 |

---

## 四、页面重构

### 4.1 登录页

> 文件：`login_page.dart` ｜ 优先级：P1 ｜ 预估：0.5 天

**现状问题**

- 每次手输设备号+PIN；无记住设备号；无指纹/生物识别
- 无"服务器地址"修改入口（`ApiConfig.load()` 有默认值，但改地址需改代码）

**新增功能**

| 功能 | 说明 |
|------|------|
| **记住设备号** | 登录成功后存 `shared_preferences`，下次自动填充 |
| **指纹/人脸解锁** | 设备已登录时，进入 App 先显示"快速解锁"页：local_auth 指纹验证通过 → 直达 HomeShell（token 已存本机） |
| **服务器地址管理** | 登录页底部"服务器设置"入口：输入 baseUrl 并存本地（与后端部署地址解耦） |

**实现要点**

```yaml
# pubspec.yaml
dependencies:
  local_auth: ^3.0.0
```

```dart
// 快速解锁（自动登录检测）
final hasToken = await store.load();
if (hasToken && await LocalAuth.canAuthenticate) {
  // 指纹失败仍可回退到 PIN 登录页
}
```

### 4.2 任务页

> 文件：`tasks_page.dart` ｜ 优先级：P1 ｜ 预估：1.5 天

**现状问题**

- 只有"今日会话列表"，无周课表/本周概览；当天无课就白屏一段
- 课程卡片无教师/地点/起止时间强化显示（后端已扩展 teacher/classroom 字段）
- 复习队列入口只是一个小入口，无到期数量角标、无提醒

**UI 布局**

```
┌──────────────────────────────┐
│ 📅 任务                        [刷新] │
├──────────────────────────────┤
│ [📖 3 节课] [⏰ 2 待复习] [🔥 6 天连续] │
│ 🔵 周一 08:00 数据结构 A101   ✓ 09:30 完成 │
│ （课程条：科目色条+名称+地点+教师）      │
├──────────────────────────────┤
│ 📅 今日复习 —— 3 项到期        [去复习] │
│ （到期知识点 chip 流式横排）            │
├──────────────────────────────┤
│ 📆 本周课表（7 行迷你条）              │
│ （周一到周日的今日高亮,周课表微缩视图） │
└──────────────────────────────┘
```

**新增功能**

| 功能 | 说明 |
|------|------|
| **统计条** | 今日节数/待复习数/连续打卡（复用 `StatPill`） |
| **课程卡增强** | 显示教师、教室、时间；课中状态图标（进行中/待开始/已结束）；完成动画勾选 |
| **复习入口升级** | 显示到期数量（red badge），点击跳 ReviewPage；全部完成显示 ✅ |
| **本周迷你课表** | 7 列小卡片（周一~周日），今天高亮；点某天看当天 3 节会话（仅展示，编辑去管理台） |
| **缓存今日会话** | `shared_preferences` 存最近一次成功结果，后端不可用时显示缓存 + 横幅提示 |

**组件拆分**

```
TasksPage → TasksHeader(统计条) + SessionCard(课程卡) + ReviewStrip(复习入口)
         + WeekStrip(迷你周课表) + FullscreenTaskView(保持现有)
```

### 4.3 课堂页

> 文件：`classroom_page.dart` ｜ 优先级：P0（拆分）+ P2（增强）｜ 预估：2 天

**现状问题**

- **1486 行单文件**：块渲染、题目卡判卷合并流、SSE 解析、错误块、手势交互全在 `_ClassroomPageState`
- 块类型多（text/quiz/question/error/…）但渲染都在一个大 `build` 里 switch
- AI 文本无 Markdown 渲染；无"上下文引用"气泡
- 无语音输入入口（`voice_input.dart` 已存在但课堂未接）

**组件拆分（核心动作）**

```
classroom_page.dart（缩减为：状态机 + 块列表编排，≈300 行）
├── widgets/block_view.dart        # 块渲染器：按 kind 分发（text/quiz/…）
├── widgets/teacher_bubble.dart    # AI 讲课气泡（右对齐用户输入 + 左对齐先生）
├── widgets/question_card.dart     # 课堂题目卡（单选/填空/简答作答态→判卷态）
├── widgets/quiz_result.dart       # 判卷结果卡（对勾/红叉+讲解）
├── widgets/error_block.dart       # 错误块（重试按钮）
└── widgets/input_bar.dart         # 输入栏（文本+语音+快捷短语 chips）
```

**增强项**

| 功能 | 说明 |
|------|------|
| **Markdown 渲染** | AI 讲课文本流式渲染（`StreamingText`），结束后切换 `MarkdownView`；代码块带复制按钮 |
| **语音输入** | 输入栏左侧话筒：`voice_input.dart` 现成能力直接接上 |
| **快捷短语** | 上下文相关 chips（"继续讲解" "出个例题" "换简单说法"），复用后端意图判别 |
| **课堂进行度** | 顶部细进度条：主线栈剩余块数 | 后端 classroom state 已有主线栈信息 |

**借鉴参考**：OpenMAIC（AI 老师+白板+讲课 TTS 的互动设计，Web 端但交互理念适用）、duoduo（AI 拆题卡的作答态设计）。

### 4.4 知识库页

> 文件：`knowledge_page.dart` ｜ 优先级：P2 ｜ 预估：2 天

**现状问题**

- 无限层级 + 热力着色 + 搜索 已达标，但：
- 树节点无：掌握度详情（进度环/最近变化）、关联题目数、描述
- 无节点详情底部抽屉、无掌握度历史
- 无拖拽调整（管理台已支持，App 仅查看）

**UI 布局**

```
┌──────────────────────────────────────────────┐
│ 🌳 知识库  (数学一 ▼)               [搜索]    │
├──────────────────────────────────────────────┤
│ [📚 数据结构] [🌐 网络] [🧮 数学一] [➕]       │
├──────────────────────────────────────────────┤
│ ▼ 📖 线性表 ▍80% [6题]          ⋮            │
│   ● 顺序表 ████░░ 60% [3题]                  │
│   ● 链表   ██████ 80% [5题]     （点节点→抽屉）│
└──────────────────────────────────────────────┘
```

**新增功能**

| 功能 | 说明 |
|------|------|
| **节点详情底部抽屉** | 点击节点弹出：描述/难易度/关联题目数/掌握度历史（复用 `mastery_records` API）/前置知识点 |
| **题目计数与跳转** | 节点旁显示题目数，点击跳到答疑/课堂问该知识点（预填 prompt） |
| **掌握度趋势** | 详情抽屉内嵌入 14 天迷你趋势条（后端 mastery_records） |
| **长按快捷操作** | 长按节点：开始复习该知识点 / 提问 AI / 导出分享 |

**借鉴参考**：engram（掌握度着色 + 力导向图可视化，若后续想上"图谱视图"可再评估）、deeprecall（对话中自动提取知识点并更新掌握度的产品逻辑）。

### 4.5 答疑聊天页

> 文件：`chat_page.dart` ｜ 优先级：P1 ｜ 预估：1.5 天

**现状问题**

- 流式纯文本渲染，长答案不可读（无 Markdown/引用）
- 三模式（free/…）入口是顶部 SegmentedControl，无模式说明文案
- 无知识点沉淀入口的显式引导（后端已支持软标注、沉淀 API）
- 无引用/来源展示（后端 RAG 检索结果未透出）

**UI 布局**

```
┌──────────────────────────────┐
│ 💬 答疑 AI    [深度模式 ▼]   │
│ (模式 chips: 自由对话/习题/复习)│
├──────────────────────────────┤
│ 🤖 先生                    ⏰ │
│  RAG 回答（Markdown 渲染，引用标号¹） │
│  [引用] 线性表定义.pdf → 展开原文      │
│ 😀 我：链表和顺序表区别？       │
│ 📍 沉淀知识点：链表 [沉淀]       │
├──────────────────────────────┤
│ [🎤] [输入…]            [发送] │
└──────────────────────────────┘
```

**新增功能**

| 功能 | 说明 |
|------|------|
| **Markdown 渲染** | 答疑流（复用 `StreamingText` + `MarkdownView`） |
| **引用展开卡** | 后端命中 RAG 片段时，消息底部展示 1-2 条引用卡片（来源名+片段摘录），点击展开 |
| **沉淀提示条** | 软标注命中时，消息尾部出现"沉淀为知识点"chip，点击调沉淀 API |
| **模式说明** | 模式切换器下加一行说明文案（如"深度模式：结合课表与知识树讲解"），借鉴 deeprecall 会话风格训练 |
| **会话管理** | 新增会话（清空当前上下文）+ 会话列表抽屉（后端已有 conversations 表） |
| **语音输入** | 接 `voice_input.dart` |

### 4.6 复习队列页

> 文件：`review_page.dart` ｜ 优先级：P1 ｜ 预估：2 天（含后端改动）

**现状问题**

- 列表式："对/错"两档按钮，无卡片翻转、无间隔预估展示
- 间隔固定 1/3/7 天，与实际作答表现无关；一次全列 3 个同等权重
- 无"今日已完成/剩余"进度感；无错题再练入口

**UI 布局**

```
┌──────────────────────────────┐
│ 🔄 今日复习 2/8 [████░░░░░]  │
<li>==========================================
│ ┌─────────────────────────┐ │
│ │ 问：什么是顺序表？         │ │
│ │  [点击显示答案]            │ │
│ │ ── 翻转后 ──              │ │
│ │ 答：顺序表是…(记忆要点)    │ │
│ │ [重做] [模糊] [记得] [清楚] │ │  ← 4 档
│ │  ▸ 下次：1 天 / 3 天 / 8 天│ │
│ └─────────────────────────┘ │
├──────────────────────────────┤
│ 今日错题：3 题 [再练一次]      │
└──────────────────────────────┘
```

**核心变更：FSRS 复习调度（替代固定 1/3/7）**

- 后端 `review` 计划由固定间隔改为 **FSRS-4.5**（开源，Anki/墨墨背单词同源算法），按每次作答记忆档位动态排期，掌握度并入 `mastery_records`
- 四档按钮：再次（重做）< 模糊 < 记得 < 清楚（对应 Anki Again/Hard/Good/Easy 语义），作答后显示**下次复习预览**
- 后端实现：`backend/app/services/review_scheduler.py`，参考开源 `fsrs4anki` 的 DSR 模型；App 只发档位，不参与算法（口径在后端，多端一致）

```python
# review_scheduler.py（示意）
from fsrs import FSRS, Card, Rating
f = FSRS()
card = Card(uid=node_id, difficulty=5.0, stability=0.0)
f.review_card(card, Rating.Good)  # → next_interval
```

| 功能 | 说明 |
|------|------|
| **四档作答** | 复用 `AnswerButtons`；无答案猜测成本（先展示答案再作答） |
| **进度条** | 顶部"今日 2/8"+进度条（复用 StatPill/ProgressBar） |
| **错题再练** | 当日答"再次/模糊"的题聚合，底部"错题再练"（同 QuizAPI 组卷） |
| **到期末推送** | 与全局推送联动（见五） |
| **到期徽标** | 任务页复习入口角标联动（见 4.2） |

**借鉴参考**：Anki/AnkiDroid（`anki/sched.py` 队列管理）、engram/GemMate/StudyRAG/SuperMemo 的 SM-2/FSRS 移动端集成（`fsrs` Dart 包提供参考实现）、deeprecall（间隔重复日历视图+逾期提醒）。

### 4.7 手写板测验页

> 文件：`handwrite_board.dart` + `handwrite_quiz_page.dart` ｜ 优先级：P2 ｜ 预估：1.5 天（含实验）

**现状问题**

- 笔画导出 PNG → 后端 LLM 看图识别：识别要等 3-8s，消耗 token，属私有 API 调用
- 手写板自身（画笔/橡皮/三色/粗细/撤销）已完善，无需重构

**方案：前端离线识别（ML Kit Digital Ink）+ 后端兜底**

- 引入 `google_mlkit_digital_ink_recognition`（支持中文 zh-Hani，离线，Gboard 同源；模型 ~10MB，首次联网下载后离线可用）
- 学生手写时把 `StrokePoint(x,y,t)` 同步收集（签名板已有点集），提交时：
  1. 先本地 ML Kit 识别候选词
  2. 候选置信度高 → 直接本地渲染候选文本问用户"是这样吗？"（候选横排点击选择）
  3. 用户确认或识别失败 → 回退现有后端识别链路（`handwrite_api.dart` 不改）
- 识别结果与手写图并排展示，便于核对

| 功能 | 说明 |
|------|------|
| **离线识别候选项** | 书写完成上滑触发识别，候选词横排显示 |
| **识别失败兜底** | ML Kit 无候选时自动走后端（提示"正在识别…"） |
| **图+文对比提交** | 提交时携带识别文本 + PNG，后端校验 |

**实验前置**：数学公式/带根号表达式识别 ML Kit 效果大概率不如大模型，所以**先用 2 天做验证：手写一个"∫eˣdx"对比两方案召回率**，再决定默认链路（决策记录 3）。

**借鉴参考**：GemMate（ML Kit + OCR 离线体验）、ML Kit 数字墨水文档（zh-Hani 模型）。

### 4.8 我的页

> 文件：`profile_page.dart` ｜ 优先级：P2 ｜ 预估：1 天

**现状问题**

- 694 行单文件；雷达图/热力图/冲刺模式/周报功能全，但难维护
- 无设置页（无深色模式开关、无服务器地址、无关于/备份）
- 数据卡与教练卡混排，无分组

**组件拆分**

```
profile_page.dart（缩减为编排，≈200 行）
├── widgets/coach_card.dart      # 教练卡
├── widgets/stats_overview.dart  # 连续天数/总学时/打卡统计
├── widgets/subject_radar.dart   # 科目掌握度雷达（复用现有绘制）
├── widgets/study_heatmap.dart   # 学习热力图（复用现有绘制）
├── widgets/sprint_card.dart     # 冲刺模式卡
└── settings_page.dart           # 设置页（新增）
```

**设置页（新增）**：深色模式开关（系统/亮/暗）、服务器地址、复习策略查看（FSRS 参数）、关于（版本号+开源协议声明——引入的第三方库需在设置页列 LICENSE）、数据备份说明。

**借鉴参考**：studytrack-app（dashboard 星级+目标进度卡）、deeprecall（学习洞察统计）。

---

## 五、全局功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **深色主题** | `AppTheme.dark` 映射 UI-SPEC 2.3；`ThemeMode` 跟随系统；设置页手动开关 | P2 |
| **本地缓存层** | `lib/core/cache.dart`：任务页最近会话/知识树最近树/答疑会话历史（每个 key 带 10 分钟 TTL），请求失败时回退 | P1 |
| **推送/本地通知** | `flutter_local_notifications`：课前 20 分钟、复习到期每日 09:00 汇总、课堂已开始（后端已有 WS 事件，App 冷启动时靠前端定闹钟即可，不依赖厂商通道） | P1 |
| **WS 重连退避** | `ws_client.dart` 增加指数退避重连；断线横幅提示"连接失效，下拉重试" | P1 |
| **全局错误收敛** | `ErrorView` 统一；API 层超时配置（15s）+ 重试 1 次；离线提示到条 | P1 |
| **无障碍** | 最小字噪 13px、按钮 ≥44dp、语音播报（学情页关键字） | P3 |
| **OTA/版本检查** | 启动时请求 `/api/v1/version` 比较本地版本，有新版本弹提示（更新指向 APK 下载地址） | P3 |

---

## 六、Flutter 设计规范

### 6.1 主题令牌（延伸 UI-SPEC）

```dart
// AppColors 保持浅色常量；深色由 ColorScheme 提供
abstract final class AppSpacing {
  static const s1 = 4.0;  static const s2 = 8.0;  static const s3 = 12.0;
  static const s4 = 16.0; static const s5 = 20.0; static const s6 = 24.0;
}
abstract final class AppRadius {
  static const xs = 4.0; static const sm = 8.0;
  static const md = 12.0; static const lg = 16.0; static const full = 999.0;
}
// 动画
abstract final class AppMotion {
  static const fast = Duration(milliseconds: 150);
  static const base = Duration(milliseconds: 250);
}
```

### 6.2 常用样式约定（对齐管理台）

| 场景 | 规格 |
|------|------|
| 卡片 | 圆角 12 / 边框 `border 0.5` / padding 14 |
| 按钮 | 主按钮高 44+；圆角 12；通栏 |
| 输入框 | 圆角 12，填充 `bgSunken`，聚焦 primary 描边 1 |
| 进度环/条 | 掌握度四档色（`masteryColor()`） |
| 底部抽屉 | 圆角 top 16 / 拖拽把手 / 禁止遮罩全黑 |
| 动画 | 位移缩放 150ms，淡入淡出 250ms，不超过 300ms |

### 6.3 代码约定

- 原页面置顶改为"数据加载三态"：`loading → error(ErrorView) → content/empty(EmptyView)`，消除重复样板
- **所有新增场景组件放 `lib/widgets/`，非页面私有仍留在 feature 内**
- 大文件以"一个页面 ≤ 400 行"为拆分红线（1486→300、694→200）

---

## 七、文件结构（目标态）

```
lib/
├── core/                     # 现有：api/chat_api/quiz_api/sse/ws/theme/auth_store
├── widgets/                  # 新增：通用组件
│   ├── section_card.dart
│   ├── stat_pill.dart
│   ├── empty_view.dart
│   ├── error_view.dart
│   ├── mastery_badge.dart
│   ├── course_pill.dart
│   ├── streaming_text.dart
│   ├── markdown_view.dart
│   ├── sheet_page.dart
│   └── answer_buttons.dart
├── features/
│   ├── shell/home_shell.dart          # 主壳（不变）
│   ├── login/login_page.dart          # +快速解锁页 quick_unlock.dart
│   ├── tasks/tasks_page.dart          # 拆 header/session_card/review_strip/week_strip
│   ├── classroom/
│   │   ├── classroom_page.dart         # 减重为编排
│   │   └── widgets/                    # block_view/teacher_bubble/question_card/…
│   ├── knowledge/knowledge_page.dart   # +node_detail_sheet.dart +mastery_history.dart
│   ├── chat/chat_page.dart             # +citation_card.dart +session_drawer.dart
│   ├── handwrite/handwrite_board.dart  # +ink_recognizer.dart
│   ├── review/
│   │   ├── review_page.dart            # 改造为卡片翻转+四档
│   │   └── widgets/rating_buttons.dart
│   └── profile/
│       ├── profile_page.dart           # 拆 coach_card/radar/heatmap/…
│       └── settings_page.dart          # 新增
└── main.dart                          # +darkTheme +ThemeMode
```

---

## 八、实施计划

| 阶段 | 内容 | 预估 | 优先级 |
|------|------|------|--------|
| **P0** | 通用组件 10 件 + `AppSpacing/AppRadius/AppMotion` 常量（6.1） | 1 天 | 最高 |
| **P0** | 课堂页拆分（1486→300），不改行为 | 1.5 天 | 高 |
| **P1** | 复习 FSRS：后端 `review_scheduler.py` + 迁移 + App 四档改造 | 2 天 | 高 |
| **P1** | 任务页增强（统计条/课程卡/复习角标/迷你周课表/缓存） | 1.5 天 | 高 |
| **P1** | 答疑增强（Markdown/引用卡/沉淀提示/会话管理/语音） | 1.5 天 | 中 |
| **P1** | 全局：缓存层 + WS 重连 + 本地通知 | 1.5 天 | 中 |
| **P2** | 知识库（节点抽屉/题目跳转/掌握度趋势） | 1 天 | 中 |
| **P2** | 我的页拆分 + 设置页（深色/服务器/关于） | 1 天 | 中 |
| **P2** | 手写离线识别（先验证后接入） | 1.5 天 | 中 |
| **P3** | 深色主题归色、无障碍、版本检查 | 1 天 | 低 |

**总计：约 14 天（可分 3 周滚动排布）**

### 依赖关系

```
P0 通用组件 ──┬──> P0 课堂拆分
              ├──> P1 答疑增强（StreamingText）
              └──> P2 我的拆分（SectionCard）
P1 复习 FSRS（后端先行）──> P1 任务页角标 + P1 本地通知
P2 手写识别：先做 0.5 天验证实验，验证后 1 天接入
```

### 每个界面的实施步骤

1. **数据确认**：确认后端 API 返回（FSRS 档位、mastery_records、conversations、citations、version）
2. **公共组件**：先补该页需要的 `widgets/*`（如 4.5 需要 StreamingText/MarkdownView）
3. **拆分/改造**：大文件先按"不动行为"拆分，再叠加新功能
4. **验证**：真机/模拟器走链路（课堂流、复习流、手写流），对照管理台行为一致

---

## 九、借鉴开源项目汇总

> 调研日期 2026-08-25，详见对话调研记录。许可已在下方标注。

### 整体产品对标

| 项目 | GitHub | 许可 | 借鉴点 |
|------|--------|------|--------|
| **StudyRAG** | github.com/dj2313/StudyRAG | MIT | Flutter+FastAPI 同构；RAG 聊天流、闪卡 SRS、进度可视化 |
| **deeprecall** | github.com/HUAyanYE/deeprecall | — | 中文学习 App：苏格拉底/费曼、掌握度评估、对话提取知识点、间隔重复日历 |
| **GemMate** | github.com/linyeping/GemMate | Apache-2.0 | 本地 Gemma + 闪卡/SM-2 + OCR + 思维导图；学习法（SM-2）移动端实践 |
| **studytrack-app** | github.com/Benmsumba/studytrack-app | — | 课表+自评+自动间隔重复调度；Dashboard 设计（本方案 4.2 统计条） |
| **duoduo 多多学** | github.com/xuanli199/duoduo | — | AI 拆题（文本/OCR→出题）、游戏化打卡、OpenAI 兼容多厂商 |
| **Studyield** | github.com/studyield/studyield | Apache-2.0 | 试卷克隆（真题风格出题）、多 agent 解题、知识图谱、费曼回讲 |

### 复习算法

| 项目 | GitHub | 借鉴点 |
|------|--------|--------|
| **Anki / AnkiDroid** | github.com/ankitects/anki | `sched.py` 队列管理参考实现；四档按钮交互 |
| **FSRS** | github.com/open-spaced-repetition/fsrs4anki | 下一代间隔重复算法（Anki 23.10+ 内置）；`fsrs` 系包已在 GemMate/engram/StudyRAG 使用 |

### 知识结构可视化

| 项目 | GitHub | 借鉴点 |
|------|--------|--------|
| **engram** | github.com/enspyrco/engram | 掌握度着色图（灰→红→琥珀→绿）与"节点亮起"反馈；后续图谱视图可参考其力导向图 |
| **Project-X** | github.com/DigitalDemi/Project-X | Flutter+Neo4j 知识点图 + 分阶段掌握度（first_time→mastered） |

### 手写识别

| 项目 | 地址 | 借鉴点 |
|------|------|--------|
| **ML Kit Digital Ink** | developers.google.com/ml-kit/vision/digital-ink-recognition | 手写识别 300+ 语言（含 zh-Hani），离线，Flutter 插件 `google_mlkit_digital_ink_recognition`；Gboard/Google 翻译同源技术 |

### AI 课堂 / 教学互动

| 项目 | GitHub | 借鉴点 |
|------|--------|--------|
| **OpenMAIC** | github.com/THU-MAIC/OpenMAIC | 多 agent 课堂（AI 老师+同学）、白板、实时 quiz 评分——课堂交互设计理念 |
| **OpenTutor / ai-shifu** | github.com/tutornew/OpenTutor | 课程编排与实时辅导 agent 概念 |

### AI 判卷

| 项目 | GitHub | 借鉴点 |
|------|--------|--------|
| **AutoSCORE** | github.com/AI4STEM-Education-Center/AutoSCORE | 双 agent：先抽评分要点 → 再打分（rubric 对齐），适合简答题评分稳定性 |
| **Auto-Essay-Grader** | github.com/Muyu-Chen/Auto-Essay-Grader | 中文作文评分 prompt（评分标准+题目） |

### 技术选型备注（不在本期）

- mind_map 思维导图（App 端暂不加，知识树为主；如需可评估 `mind_map_flutter` 库或 engram 力导向图）
- 端侧 LLM（Gemma）/离线兜底 API：本期不做，留给后续 P3+（与成本、网络环境相关）
- Flutter 状态管理（Riverpod/BLoC）：**决策不引入**，理由见十

---

## 十一、管理台配套改动（联动项）

> 管理台「前端重构方案.md」已落地或规划中，本节仅列 **App 本次更新需要的管理台/后端联动**，避免各端口径漂移。

### 11.1 需后端配合的 API（App 已引用）

| 接口 | 状态 | 说明 |
|------|------|------|
| `POST /api/v1/review/:id/rate` | 新增 | FSRS 四档（0 重做/1 模糊/2 记得/3 清楚），替代原对/错口径 |
| `GET /api/v1/knowledge/:id/mastery-history` | 已有基础 | `mastery_records` 表直接可查，App 知识库抽屉用 |
| `GET /api/v1/chat/:conversation/citations` | 新增或复用 | 答疑引用片段，供引用卡展示 |
| `GET /api/v1/version` | 新增 | App 版本检查（轻微） |
| 现有 `/api/v1/classroom/state` | 不改 | 主线栈剩余块数用于课堂进度条 |

### 11.2 管理台页面联动点

- **复习策略设置**：管理台「AI 设置」或新建「复习策略」页：FSRS 参数（目标保持率 0.9、每日新卡上限、默认档位），修改后 App 生效；对接复用现有 settings 接口模式
- **科目/资源字段**：后端更新方案已为 `courses.icon/description/is_archived`、`schedule_items.teacher/classroom` 预留；管理台课程卡片/课表网格已展示 → App 任务卡直接读取展示（4.2）
- **通知提醒**：管理台如增加"提醒时间设置"（课前 N 分钟、复习时间点），与 App 本地通知共用 localStorage/设置接口
- **审计日志**：管理台已加审计日志查看；App 侧操作（复习 rate、沉淀）将写入后端 audit（软标注相关）

### 11.3 节奏建议

管理台与 App 并行推进时按此顺序交付，减少返工：
1. 后端 FSRS 调度 + rate API（P1 前置）
2. App 通用组件 + 课堂拆分（不依赖后端）
3. 管理台复习策略设置页（依赖 1）
4. App 复习四档改造（依赖 1）
5. App 手写识别实验（独立）

---

## 十、关键决策记录

### 决策 1：不引入状态管理/路由库

**原因**：现有 8 个页面 + 12 个 core 模块全部 `setState` 驱动且运行稳定（课堂/答疑流式、WS 更新都已验证）；引入 Riverpod 需重写全部页面，风险远大于收益。保留 `homeTabIndex` 的 `ValueNotifier` 模式即可支持本次改造（Tab 深链、复习角标更新均为"通知→重载"模式，与现状一致）。

### 决策 2：FSRS 口径放在后端，App 只发档位

**原因**：
- 切换策略、调参、记录 logging 全在服务端，保证 App/管理台/多端一致
- 复习记录与 `mastery_records` 统一由后端写，审计可查
- 若前端算 FSRS，排程随版本漂移会出双记账问题

**实现要点**：后端建 `review_scheduler.py`（纯函数，入参 node_id → 出参 interval/mastery 增量）+ `mastery_records` 落库；API 增加 `POST /api/v1/review/:id/rate`（档位 0-3）。App `quiz_api.dart` 增加 `reviewRate()`。

### 决策 3：手写识别"先实验后接入"

**原因**：ML Kit 数字墨水对中文整字识别好，但对数学表达式/根号/积分等符号的召回不确定。先实现 0.5 天 POC：同一组手写题目分别走 ML Kit 与现后端 LLM，统计 Top-3 召回率；召回 ≥85% 才作为默认链路，否则维持后端识别、ML Kit 只作为候选项提示。

### 决策 4：课堂/答疑共用 StreamingText + MarkdownView

**原因**：两端产生同一形态内容（SSE 增量文本 + 富格式答案），合并一个组件减少一半维护面；流式阶段轻量渲染（Text 拼接），结束才转 Markdown/代码块，避免流式期间正则重排版。

### 决策 5：通知用本地定时而非服务端推送

**原因**：当前部署为家庭局域网/自托管场景，无厂商推送通道（FCM 等）；本地 `flutter_local_notifications` 按账号课表提醒 15 分钟级即可满足；后端已通过 WS 推实时态，冷启动场景用本地闹钟补齐。

---

*文档结束*
