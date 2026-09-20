# AGENTS.md — 多 Agent 并发协作约定

> 本项目可能同时有 **opencode（Claude Code）** 与 **Doubao（豆包）** 两个 AI 助手在操作同一个工作区（`C:\creategame\AI学` 后端 + `C:\ailearn\app` Flutter）。
> **任何 Agent 进入本工作区必须先读本文件**，并遵守下面的协作约定，避免互相覆盖、踩冲突。

## 铁律

1. **动手改文件前，先声明占用**：更新 `.agent-status.json`，写明你是谁（`opencode` / `doubao`）、要改哪些文件、预计完成时间。改完**必须释放**（置 `idle`）。
2. **读文件/构建/跑测试前，先看一眼状态**：若对方正持有你需要的文件锁，先等或问，不要硬改。
3. **同一文件绝不两个 Agent 同时写**。需要改对方正持有的文件时，先读状态，必要时在对话里问用户协调。
4. **不删对方的产物**：`prototype/`、`docs/`、`admin/` 等若对方近期在改，先确认再动。
5. **后端/App 是共享资源**：重启后端、构建 APK、改 AI 配置前，先写状态声明，避免两个 Agent 各起一个后端端口冲突。
6. **DB 是共享的**：SQLite 加锁弱，两个 Agent 同时写事务可能 `database is locked`。写 DB 前先声明，写完即释放。

## .agent-status.json 格式

```json
{
  "last_updated": "2026-08-24T23:40:00+08:00",
  "active": {
    "agent": "opencode | doubao",
    "task": "正在做什么的一句话描述",
    "files": ["相对路径数组，正在改的文件"],
    "holds_backend": true,
    "since": "ISO 时间"
  }
}
```

- `active.agent` 为 `null` / `idle` 表示无占用，可以自由操作。
- 记录**当前唯一活跃方**；若发现已被对方占用，不要覆盖，等其释放或询问用户。

## 快速约定

- 占用：`opencode` 改 `backend/app/services/classroom.py` → 先写 `active.agent=opencode, files=[...]`
- 释放：任务完成后把 `active.agent` 置 `null`
- 冲突：`.agent-status.json` 里对方正在改你要改的文件 → **先停下问用户**，绝不盲改

## 建议分工

- **opencode（本会话）**：默认负责 Flutter App 端（`C:\ailearn\app`）+ 课堂/答题链路。
- **Doubao（豆包）**：默认负责后端 AI 通道/管理台/数据（如近期在改 `ai_gateway.py`、`call_logger.py`、`admin/`）。
- 交叉改动前务必走状态声明。
