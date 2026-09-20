# backend/seeds —— 知识内容种子数据

知识点与题目的**可入库形态**。这个目录存在的理由很具体：这两类资产此前只躺在
`backend/data/users/<user>.db` 里，而 `backend/data/` 被 `.gitignore` 整目录排除
（那里同时装着 `users.pin_hash` / `token_hash` 和做题记录、对话等内容）——
**知识内容被个人隐私连坐，一直没进版本管理**。这里把它们拆出来单独版本化。

## 内容

| 库 | 知识点 | 题目 | 含专业化参数 | 含摘要 |
|---|---:|---:|---:|---:|
| `eggli` | 1087 | 2572 | 813 | 973 |
| `dangdang` | 786 | 333 | 0 | 49 |
| **合计** | **1873** | **2905** | 813 | 1022 |

科目构成：

- **eggli** —— 数据结构、高等数学、计算机组成原理、操作系统、计算机网络（408 四科 + 数学）
- **dangdang** —— 数学分析（华东师大第五版）、高等代数（北大王萼芳版）、英语一

题目题型：单选 2898、判断 3、填空 3、简答 1。

## 文件

```
seeds/
├── manifest.json                              # 总清单（条数、导出时间、逐库统计）
├── knowledge/
│   ├── eggli.knowledge_nodes.json             # 完整知识点树（嵌套 params）
│   ├── eggli.knowledge_nodes.csv              # 扁平表格，便于人读/审阅
│   ├── dangdang.knowledge_nodes.json
│   └── dangdang.knowledge_nodes.csv
└── quiz/
    ├── eggli.quiz_questions.json              # 完整题目 v2.0 契约对象
    ├── eggli.quiz_questions.csv               # 索引：题面/选项/答案/解析
    ├── dangdang.quiz_questions.json
    └── dangdang.quiz_questions.csv
```

CSV 一律 **UTF-8 带 BOM**（Excel 直接双击打开中文不乱码）。列表类字段（如 `key_terms`）
在 CSV 里用 ` | ` 连接，完整结构以 JSON 为准。

## ⚠️ id 空间：两库独立，不可跨库关联

两个库的 `id` **各自从 1 开始，且语义不同**——

| | `id = 1` 是什么 |
|---|---|
| `eggli` | 「第1章 绪论」（数据结构） |
| `dangdang` | 「数学分析」 |

`quiz_questions.node_id` 指向**同库的** `knowledge_nodes.id`。所以**不要**把两个库合并
重编号，那会切断题目与知识点的关联。要区分同名 id，请带上 `subject_name` 或库名前缀。

## 隐私边界：什么被拿掉了

导出时刻意剥离了三个字段——它们是「某人对某知识点的掌握情况」，属个人学习状态：

| 库 | 被剥离的取值 |
|---|---|
| `eggli` | `mastery`（5: 132 / 0: 955）、`status`（learning: 132 / untouched: 955）、`quiz_ids`（全空） |
| `dangdang` | `mastery`（全 0）、`status`（全 untouched）、`quiz_ids`（全空） |

**完全未导出**的表：`users`（含 `pin_hash` / `token_hash` / `db_key`）、`mastery_records`、
`quiz_answers`、`quiz_sessions`、`quiz_session_items`、`conversations`、`messages`、
`study_sessions`、`tasks`、`schedule_*`、`review_queue`、`course_memories`。

校验由 `scripts/check_seeds.py` 强制把关（18 项断言，含字段名黑名单扫描）。

### `notes` 为什么保留了

`knowledge_nodes.notes` 名字像个人笔记，实际是**知识点专业化参数**的 JSON：

```json
{"schema_version": "1.0", "refined_at": "2026-08-27T13:34:19Z",
 "params": {"definition": "...", "core_elements": [...], "key_terms": [...],
            "formulas": [...], "common_mistakes": [...],
            "scope_boundary": "...", "prerequisites_desc": "..."},
 "params_status": "valid", "content_errors": []}
```

它与 `docs/params_csv/` 下那 30 个 CSV **同源且一一对应**（实测交集 813/813，
CSV 侧多 2 条未在库中落地）。导出时解析进 JSON 的 `params` 字段，字段值无损。

## 字段

**知识点**（JSON `nodes[]`）

| 字段 | 说明 |
|---|---|
| `id` / `parent_id` | 树结构，库内原始 id |
| `subject_id` / `subject_name` | 科目。库中没有 subjects 字典表，`subject_name` 由根节点名称与教材章节名推断，可能需人工校正 |
| `name` / `level` | 名称与层级（1 科目根 / 2 章 / 3 节 / 4 知识点） |
| `difficulty` | 难度 1–5 |
| `source` | 来源：`import`、`import_408`、`manual` |
| `summary` / `prerequisites` | 摘要与前置知识 |
| `params` | 专业化参数，见上 |

**题目**（JSON `questions[]`）

| 字段 | 说明 |
|---|---|
| `id` / `node_id` / `node_name` | 题目 id 与所挂知识点 |
| `qtype` / `difficulty` | 题型与难度 |
| `payload` | 题目 v2.0 契约对象：`question` / `options` / `blanks` / `content` / `segments` / `ladder_steps` / `correct_answer` / `explanation` / `analysis` / `points` / `generation_meta` |

`generation_meta` 是生成审计信息，占 payload 约 33%，保留以便追溯 AI 生成过程。

## 重新生成

```bash
cd backend
python scripts/export_seeds.py          # 全量导出
python scripts/export_seeds.py eggli    # 只导指定库
python scripts/check_seeds.py           # 校验（18 项断言）
```

导出脚本以**只读模式**打开用户库（`?mode=ro`），不会抢生产库的写锁，也不会改动源数据。

## 已知问题

1. **1 条题目是孤儿**：`eggli` 中 `id` 最小的那条题目 `node_id` 为 `NULL`，挂不上任何知识点。
   这是库里原本就有的状态，非导出造成。数量已在 `check_seeds.py` 里断言锁定，不会悄悄扩大。
2. **`subject_name` 是推断值**：库里没有科目字典表，映射写在 `export_seeds.py` 的
   `SUBJECT_NAMES` 常量里。若发现科目归属有误，改那里再重新导出。
3. **这是快照，不是实时源**：修改学习内容后需重跑导出，种子文件才会同步。
