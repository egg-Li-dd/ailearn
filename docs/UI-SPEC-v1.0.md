# ai学 UI 设计规范 v1.0

> 高保真 UI 原型用 CSS 实现（浏览器先行），Flutter 实现时同一规范映射为 ThemeData。
> 本规范所有数值可直接用于 CSS / Flutter / Vue。

---

## 1. 设计理念

**关键词**：晨光、专注、纸感、克制
- 学习场景的界面应安静不打扰：浅色纸感基底为主，深色模式为可选开关
- AI 是"教练"不是"炫技"：AI 元素用统一的辅助色点缀，不喧宾夺主
- 数据（掌握度、进度）用颜色直接说话：热力着色一眼可读
- 一切动效克制：位移/缩放 ≤ 150ms，淡入淡出 ≤ 300ms，无弹跳
- 8pt 网格：所有间距、圆角、尺寸取 4 的倍数

## 2. 色彩系统

### 2.1 浅色主题（默认）

| Token | 色值 | 用途 |
|---|---|---|
| --bg | #F6F6F2 | 页面基底（暖纸感） |
| --bg-card | #FFFFFF | 卡片面 |
| --bg-sunken | #EEEDE8 | 下沉区（输入框、代码块底） |
| --text | #1C1B1A | 主文字（近黑带暖） |
| --text-secondary | #5C5A55 | 次级文字 |
| --text-muted | #908D85 | 弱化文字/占位 |
| --border | #E3E1DA | 分隔线/描边 |
| --primary | #3E63DD | 主色：专注蓝（按钮、选中、链接） |
| --primary-weak | #E9EEFB | 主色浅底（标签、选中背景） |
| --ai | #8A5CD6 | AI 元素色（AI 气泡、AI 生成标记） |
| --ai-weak | #F1EBF9 | AI 浅底 |
| --danger | #C24238 | 错误、逾期 |
| --warning | #C77E1E | 警告、学习中状态 |
| --success | #3E8E58 | 成功、已掌握 |

### 2.2 掌握度四档色（知识树热力）

| 状态 | 色值 | 图标/着色 |
|---|---|---|
| 未学 | #A8A69F（灰） | 空心圆点 |
| 学习中 | #C77E1E（琥珀） | 进度环 1/3 |
| 已掌握 | #3E8E58（青绿） | 进度环 2/3 |
| 待复习 | #C24238（红） | 进度环 1/3 + 脉冲点 |

编码规则：掌握度 0-39 灰、40-69 琥珀、70-84 绿、85+ 深绿（#2E6E42），待复习>7天转红。

### 2.3 深色主题（可选开关，实现后置）

| Token | 色值 |
|---|---|
| --bg | #14151A |
| --bg-card | #1D1F26 |
| --bg-sunken | #262932 |
| --text | #ECEBE6 |
| --text-secondary | #A9A7A0 |
| --text-muted | #6F6D67 |
| --border | #33363F |
| --primary | #6E8FF0 |
| --primary-weak | #232B45 |
| --ai | #A583E8 |
| --ai-weak | #2A2440 |

### 2.4 科目配色（颜色即科目，全端复用）

| Token | 科目 | 色值 |
|---|---|---|
| --subj-ds | 数据结构 | var(--primary) 蓝 |
| --subj-co | 组成原理 | var(--ai) 紫 |
| --subj-os | 操作系统 | var(--success) 绿 |
| --subj-net | 计算机网络 | var(--warning) 琥珀 |
| --subj-math | 数学一 | var(--danger) 红 |
| --subj-en | 英语一 | #5C5A55 墨灰 |
| --subj-politics | 政治 | #A8A69F 浅灰 |

应用：知识库科目 chips、雷达图图例、任务卡科目色条、管理台课程标识。深色主题下英语一/政治用对应文字色继承。

### 2.5 语义弱底（标签·横幅·渐变底）

| Token | 色值 | 用途 |
|---|---|---|
| --danger-weak / -deep / -border | #FFF5F5 / #FFE8E8 / #F5D0D0 | 冲刺卡、纠错标签 |
| --success-weak | #E8F5EC | 答对态、结论标签 |
| --warning-weak / -deep / -border | #FFF8EC / #FFF3DC / #F0DFB8 | 课前横幅 |
| --ai-border | #E0D4F5 | 沉淀卡描边 |
| --ai-tint | #F8F7FF | AI 系淡底渐变 |
| --bg-tint | #EDEDF0 | 页面淡渐变 |

## 3. 字体与字阶

字体栈（CSS）：
```css
--font-sans: "PingFang SC", "HarmonyOS Sans SC", "MiSans", "Noto Sans SC", "Microsoft YaHei", sans-serif;
--font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
```
数字统一 `font-variant-numeric: tabular-nums`（表格式对齐）。

| Token | 尺寸/行高/字重 | 用途 |
|---|---|---|
| --fs-display | 28/36/600 | 课中模式目标大数字、掌握度大数字 |
| --fs-h1 | 22/30/600 | 页面大标题 |
| --fs-h2 | 17/24/600 | 卡片标题 |
| --fs-body | 15/22/400 | 正文、消息 |
| --fs-secondary | 13/18/400 | 次级信息 |
| --fs-caption | 12/16/400 | 辅助标注、标签 |

品牌例外：入口页（index）品牌大标题允许 36px/600，仅限该处。

## 4. 间距 · 圆角 · 阴影（8pt 网格）

| Token | 值 | 用途 |
|---|---|---|
| --space-xs | 4 | 图标内距 |
| --space-sm | 8 | 标签内距、元素间隔 |
| --space-md | 16 | 卡片内边距、列表项间隔 |
| --space-lg | 24 | 区块间隔 |
| --radius-sm | 8 | 小件（标签、输入框、按钮） |
| --radius-md | 12 | 卡片、气泡、弹窗 |
| --radius-lg | 20 | 底部弹层、大图卡 |
| --shadow-card | 0 1px 2px rgba(0,0,0,.04), 0 2px 8px rgba(0,0,0,.06) | 卡片浮起（浅色主题） |
| --shadow-float | 0 4px 16px rgba(0,0,0,.10) | 弹窗、底部栏 |
| --shadow-none | 无 | 深色主题用分层代替阴影 |

## 5. 组件规范

### 5.1 任务卡片（任务界面核心）
- 结构：`[类型图标] 标题 … [时长] [状态]`，左侧 3px 类型色条
- 类型色：阅读=primary、练习=ai、记忆=warning、思考=success、复习=danger
- 状态：未开始（灰描边）、进行中（主色描边+标题加粗）、完成（打勾图标，成功率配色）、跳过（虚化）
- 完成态动效：对勾 150ms 缩放出现 + 卡片背景闪 primary-weak 300ms

### 5.2 聊天气泡（答疑界面）
- 用户：primary-weak 底、圆角 12 偏右，右下 4px 小角
- AI：--bg-card + --border 描边，左侧 AI 标记（紫色小圆点 + "教练"）
- 流式：AI 输出尾部光标"▍"闪烁；完成后光标消失
- 知识点标注：AI 气泡内嵌标签 chip（--ai-weak 底、--ai 字），点击跳知识树节点
- 样式：`<span class="knode" data-node-id="...">知识点名</span>`

### 5.3 知识树节点
- 结构：节点行 = 状态圆点/进度环 + 名称 + (难度徽标) + 掌握度数字
- 展开行：左侧竖线层级缩进 20px/级
- 掌握度热力：节点名颜色按四档着色
- 难度徽标：1-2 浅（--text-muted）、3（--warning）、4-5（--danger），小星形图标

### 5.4 教练卡片（我的界面）
- 头部：圆形头像（渐变 primary→ai）+ 名称 + 每日寄语（--text-secondary，斜体可选）
- 数据组：连续天数、本周学时两枚大数字（--fs-display，primary 色）
- 雷达图：7 科掌握度，primary 填充 0.08 透明度
- 热力图：GitHub 风格，色阶 = 掌握度四档色之绿系透明渐变（复用 --success 家族）

### 5.5 通用组件
- 底部 Tab 栏：4 Tab（任务/答疑/知识库/我的），选中态 primary 图标+文字，未选中 --text-muted；iOS 安全区垫底
- 按钮：主按钮 primary 底白字 15/圆角12 高44；次按钮白底描边 --border 主色字
- 输入框：--bg-sunken 底、圆角 12、聚焦时 1px primary 描边
- 进度环（掌握度）：stroke-width 6，圆角端点，色随四档
- 骨架屏：--bg-sunken 块 + 呼吸淡入淡出 1.2s 循环
- 空状态：居中插画（简单线性）+ 一句提示（--text-muted）

### 5.6 组件库承载

全部原型组件（任务卡、气泡、树节点、分段控件、进度环、FAB、全屏模式、手机外壳等）统一收录于 `prototype/design-tokens.css`，页面复用，禁止页面内自行发明组件样式。组件清单随设计迭代在 tokens 文件中同步维护。

## 6. 页面布局

### 6.1 任务界面
- 常态：顶部日期+今日课程头卡（课程名、时间、科目色条）→ 任务卡片列表 → 底部"问教练"浮动按钮
- 课中模式（全屏）：无 Tab 栏；顶部渐变头（primary → #5B7EE8，登记为 --primary-grad-end 未引入前以字面值使用）+ 倒计时 + 本课目标（h1）→ 中间当前任务大卡（其余任务暗化）→ 底部"完成本任务/问教练"两个主按钮；300ms 从常态淡入全屏
- 课前模式：同上结构，顶部替换为"距上课 N 分钟"

### 6.2 答疑界面
- 顶部：会话模式切换（自由问 | 做题 | 小测）三段式 segmented
- 消息列表：气泡 + 时间戳（--fs-caption）
- 底部：输入框 + 发送钮；输入中可插"知识点"引用 chip

### 6.3 知识库界面
- 顶部：科目横向筛选 chips（7 科可滚动）+ 搜索框
- 主体：树状列表（见 5.3）
- 过滤：右上角图标打开底部弹层：按难度 1-5 / 状态过滤

### 6.4 我的界面
- 教练卡片（5.4）→ 复习队列卡（今日 N 题，danger 角标）→ 雷达图卡 → 热力图卡 → 设置入口列表（chevron 箭头）

### 6.5 管理台（Web）
- 布局：左侧 180px 导航（课程表/知识树/任务配置/AI 设置/数据），右侧内容区
- 风格：与 App 同色板；表格 13px 字号、行高 40、斑马纹 --bg-sunken 淡；表单控件同 App 规范
- 移动端不重点适配（电脑使用）

## 7. 动效规范

| 场景 | 时长 | 曲线 |
|---|---|---|
| 页面切换 | 200ms | ease-out 透明度+8px 位移 |
| 全屏切换（课中） | 300ms | ease-out 淡入 |
| 任务完成对勾 | 150ms | scale 0.8→1 + 底闪 |
| 流式打字 | 每秒 30-45 字 | 恒定，非等宽 |
| 掌握度更新 | 300ms | 数字滚动 + 节点脉冲(透明度 0.4→1) |
| 推送提醒（复习到期） | 250ms | 顶部横幅滑入 |
| 骨架屏 | 1.2s 循环 | 透明 0.4↔0.8 |

## 8. CSS 变量清单（原型直接可用）

```css
:root {
  /* paper */
  --bg: #F6F6F2; --bg-card: #FFFFFF; --bg-sunken: #EEEDE8;
  /* ink */
  --text: #1C1B1A; --text-secondary: #5C5A55; --text-muted: #908D85;
  --border: #E3E1DA;
  /* accent */
  --primary: #3E63DD; --primary-weak: #E9EEFB;
  --ai: #8A5CD6; --ai-weak: #F1EBF9;
  --danger: #C24238; --warning: #C77E1E; --success: #3E8E58; --success-deep: #2E6E42;
  /* mastery */
  --m-untouched: #A8A69F; --m-learning: #C77E1E; --m-mastered: #3E8E58; --m-review: #C24238;
  /* type */
  --font-sans: "PingFang SC", "HarmonyOS Sans SC", "MiSans", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
  /* spacing & radius & shadow */
  --space-xs: 4px; --space-sm: 8px; --space-md: 16px; --space-lg: 24px;
  --radius-sm: 8px; --radius-md: 12px; --radius-lg: 20px;
  --shadow-card: 0 1px 2px rgba(0,0,0,.04), 0 2px 8px rgba(0,0,0,.06);
  --shadow-float: 0 4px 16px rgba(0,0,0,.10);
}
[data-theme="dark"] { /* 深色覆盖，见 2.3 */ }
```

## 9. Flutter 映射说明（实现阶段）

- CSS 变量 → ThemeData：ColorScheme（primary/secondary/error/surface）+ 自定义 extension
- 空间/圆角 → 全局常量类 AppSpacing / AppRadius
- 字阶 → TextTheme（displayLarge..labelSmall）
- 阴影 → 无，用 elevation 分层
- 掌握度四档 → MasteryColor enum，树节点/进度环统一取色
- 深色主题 → ThemeMode.system 双 ThemeData

## 10. 原型制作顺序建议

1. 任务界面（常态 + 课前 + 课中全屏）— 核心场景
2. 答疑界面（三模式 + 流式 + 知识点 chip）
3. 知识库（树 + 热力 + 过滤）
4. 我的界面（教练卡 + 雷达 + 热力图）
5. 管理台（课程表 + 知识树两屏）
6. 深色主题覆盖验证

每个页面做成独立 HTML 文件放 `prototype/`，用同一份 `design-tokens.css` 引用，保证变量单一来源。