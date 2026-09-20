"""导出「知识内容」种子数据（知识点 + 题目）为可入库的 JSON/CSV。

## 为什么需要这个脚本

知识点与题目此前只存在于 `backend/data/users/<user>.db` 里，而 `backend/data/`
被 .gitignore 整目录排除——因为里面同时装着 `users.pin_hash` / `users.token_hash`
以及做题记录、对话等内容。结果是「知识内容」被「个人隐私」连坐，无法进版本管理。

本脚本把两者拆开：只导出知识内容，不导出任何个人状态。

## 隐私边界（硬性，改动前先想清楚）

- **剥离** `knowledge_nodes.mastery` / `status` / `quiz_ids`——这三列是「某人对某知识点的
  掌握情况」，属于个人学习状态
- **不碰** `users` / `mastery_records` / `quiz_answers` / `quiz_sessions` /
  `quiz_session_items` / `conversations` / `messages` / `study_sessions` 等表
- `knowledge_nodes.notes` **保留**：它不是笔记，而是知识点专业化参数
  （definition / core_elements / key_terms / formulas / common_mistakes 的 JSON），
  与 `docs/params_csv/` 那批 CSV 同源，属纯知识内容
- 题目 `payload_json` 整体保留（实测 0 条命中密钥类敏感词）

## 为什么不合并成一个库

两个用户库的 `id` 各自从 1 开始，**且语义不同**（eggli 的 id=1 是「第1章 绪论」，
dangdang 的 id=1 是「数学分析」）。而 `quiz_questions.node_id` 指向
`knowledge_nodes.id`——一旦重新编号，题目与知识点的关联就断了。
所以按库分开导出，各自保留原始 id 空间。

## 用法

    cd backend
    python scripts/export_seeds.py              # 导出全部用户库
    python scripts/export_seeds.py eggli        # 只导指定库
    python scripts/export_seeds.py --out ../dist/seeds   # 换个输出目录
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_USERS_DIR = BACKEND_DIR / "data" / "users"
DEFAULT_OUT_DIR = BACKEND_DIR / "seeds"

SCHEMA_VERSION = "1.0"

# subject_id → 科目名。库里没有 subjects 字典表（subject_id 是导入时硬编码的），
# 以下映射由各 subject 下的根节点名称与教材章节名推断得出：
#   eggli    — 数据结构(第1章 绪论) / 高等数学(第1章 函数与极限) /
#              计算机网络(第1章 概述) / 操作系统(第1章 计算机系统概述) /
#              计算机组成原理(第1章 计算机系统概论)，另有一套 import_408 的科目根节点可互证
#   dangdang — 根节点直接就是科目名
SUBJECT_NAMES: dict[str, dict[int, str]] = {
    "eggli": {
        1: "数据结构",
        2: "高等数学",
        4: "计算机网络",
        5: "操作系统",
        6: "计算机组成原理",
    },
    "dangdang": {
        1: "数学分析",
        2: "高等代数",
        3: "英语一",
    },
}

# 知识点导出列（刻意不含 mastery / status / quiz_ids）
KNOWLEDGE_COLUMNS = (
    "id", "parent_id", "subject_id", "name", "level", "difficulty",
    "source", "summary", "prerequisites", "sort", "icon", "created_at", "notes",
)


def open_ro(db_path: Path) -> sqlite3.Connection:
    """只读打开用户库。

    生产库可能正被后端进程持有（含 -wal / -shm），只读模式可避免抢写锁，
    也避免误改源数据。
    """
    uri = "file:" + quote(str(db_path).replace("\\", "/"), safe="/:") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def parse_notes(raw: str | None) -> dict | None:
    """把 notes 里的专业化参数 JSON 解出来。

    容错：早期数据可能存的是无法解析的文本，此时原样返回 {"raw": ...}，
    宁可留下脏数据痕迹，也不要静默丢弃。
    """
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        return {"raw": raw}
    if not isinstance(obj, dict):
        return {"raw": raw}
    return obj


def export_knowledge(con: sqlite3.Connection, lib: str) -> tuple[list[dict], dict]:
    """导出知识点，返回 (节点列表, 统计)。"""
    cur = con.execute(
        f"select {', '.join(KNOWLEDGE_COLUMNS)} from knowledge_nodes order by id"
    )
    subs = SUBJECT_NAMES.get(lib, {})
    nodes: list[dict] = []
    stat = {"with_params": 0, "with_summary": 0, "unparsable_notes": 0}

    for row in cur:
        rec = dict(zip(KNOWLEDGE_COLUMNS, row))
        notes = parse_notes(rec.pop("notes"))
        if notes:
            if "raw" in notes:
                stat["unparsable_notes"] += 1
            else:
                stat["with_params"] += 1
        if rec.get("summary"):
            stat["with_summary"] += 1
        rec["subject_name"] = subs.get(rec.get("subject_id"))
        if notes:
            rec["params"] = notes
        nodes.append(rec)

    stat["count"] = len(nodes)
    return nodes, stat


def export_quiz(con: sqlite3.Connection, nodes: list[dict]) -> tuple[list[dict], dict]:
    """导出题目，payload 解析为对象（避免 JSON 字符串双重转义）。"""
    name_of = {n["id"]: n["name"] for n in nodes}
    subj_of = {n["id"]: n["subject_name"] for n in nodes}
    cur = con.execute(
        "select id, node_id, difficulty, qtype, payload_json, created_at "
        "from quiz_questions order by id"
    )
    items: list[dict] = []
    stat = {"count": 0, "unparsable_payload": 0, "orphan_node": 0}
    qtypes: dict[str, int] = {}

    for qid, node_id, difficulty, qtype, payload, created_at in cur:
        if node_id not in name_of:
            stat["orphan_node"] += 1
        try:
            body = json.loads(payload) if payload else None
        except (TypeError, ValueError):
            body = {"raw": payload}
            stat["unparsable_payload"] += 1
        qtypes[qtype or "?"] = qtypes.get(qtype or "?", 0) + 1
        items.append({
            "id": qid,
            "node_id": node_id,
            "node_name": name_of.get(node_id),
            "subject_name": subj_of.get(node_id),
            "difficulty": difficulty,
            "qtype": qtype,
            "created_at": created_at,
            "payload": body,
        })

    stat["count"] = len(items)
    stat["qtypes"] = qtypes
    return items, stat


def write_json(path: Path, payload: dict) -> int:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return path.stat().st_size


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> int:
    """UTF-8 **带 BOM**——Excel 打开中文 CSV 时不带 BOM 会乱码。"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k) for k in columns})
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    return path.stat().st_size


def flatten_params(node: dict) -> dict:
    """把 params 里的字段摊平，供 CSV 使用（列表用 | 连接）。"""
    p = node.get("params") or {}
    out = {}
    for key in ("definition", "scope_boundary", "prerequisites_desc"):
        v = p.get(key)
        out[key] = v if isinstance(v, str) else ("" if v is None else str(v))
    for key in ("core_elements", "key_terms", "formulas", "common_mistakes"):
        v = p.get(key)
        if isinstance(v, list):
            out[key] = " | ".join(str(x) for x in v)
        else:
            out[key] = "" if v is None else str(v)
    out["params_status"] = p.get("params_status", "")
    return out


def question_csv_row(item: dict) -> dict:
    body = item.get("payload") or {}
    if not isinstance(body, dict):
        body = {}
    options = body.get("options")
    if isinstance(options, list):
        options = " | ".join(f"{chr(65+i)}. {o}" for i, o in enumerate(options))
    else:
        options = ""
    return {
        "id": item["id"],
        "node_id": item["node_id"],
        "node_name": item.get("node_name") or "",
        "subject_name": item.get("subject_name") or "",
        "qtype": item.get("qtype") or "",
        "difficulty": item.get("difficulty"),
        "points": body.get("points"),
        "ladder_steps": body.get("ladder_steps"),
        "correct_answer": body.get("correct_answer"),
        "question": body.get("question") or body.get("content") or "",
        "options": options,
        "explanation": body.get("explanation") or "",
        "generated_by": (body.get("generation_meta") or {}).get("source", "")
        if isinstance(body.get("generation_meta"), dict) else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="导出知识点与题目种子数据")
    ap.add_argument("libs", nargs="*", help="要导出的库名（默认全部）")
    ap.add_argument("--users-dir", default=str(DEFAULT_USERS_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    users_dir = Path(args.users_dir)
    out_dir = Path(args.out)
    if not users_dir.is_dir():
        print(f"错误：用户库目录不存在：{users_dir}")
        return 1

    # 跳过 0 字节的空库（如 legacy_*.db 之外的残留文件）
    all_dbs = sorted(p for p in users_dir.glob("*.db") if p.stat().st_size > 0)
    targets = [p for p in all_dbs if not args.libs or p.stem in args.libs]
    if not targets:
        print(f"错误：没有可导出的库（候选：{[p.stem for p in all_dbs]}）")
        return 1

    exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    (out_dir / "knowledge").mkdir(parents=True, exist_ok=True)
    (out_dir / "quiz").mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []

    for db_path in targets:
        lib = db_path.stem
        print(f"\n{'='*66}\n库：{lib}  ({db_path.stat().st_size/1024/1024:.2f} MB)\n{'='*66}")
        con = open_ro(db_path)
        try:
            nodes, kstat = export_knowledge(con, lib)
            quizzes, qstat = export_quiz(con, nodes)
        finally:
            con.close()

        if not nodes:
            print("  （无知识点，跳过）")
            continue

        # ── 知识点 ──
        k_json = out_dir / "knowledge" / f"{lib}.knowledge_nodes.json"
        write_json(k_json, {
            "schema_version": SCHEMA_VERSION,
            "exported_at": exported_at,
            "source_library": lib,
            "source_file": f"backend/data/users/{lib}.db",
            "notice": "已剥离个人学习状态字段（mastery / status / quiz_ids）。"
                      "id 为该库原始 id，与同目录 quiz 文件的 node_id 对应，请勿重编号。",
            "subject_names": {str(k): v for k, v in SUBJECT_NAMES.get(lib, {}).items()},
            "count": len(nodes),
            "nodes": nodes,
        })
        k_csv = out_dir / "knowledge" / f"{lib}.knowledge_nodes.csv"
        k_rows = [{**n, **flatten_params(n)} for n in nodes]
        write_csv(k_csv, k_rows, [
            "id", "parent_id", "subject_id", "subject_name", "name", "level",
            "difficulty", "source", "summary", "definition", "core_elements",
            "key_terms", "formulas", "common_mistakes", "scope_boundary",
            "prerequisites_desc", "params_status", "prerequisites", "sort", "icon",
            "created_at",
        ])
        print(f"  知识点 {len(nodes)} 条"
              f"（含专业化参数 {kstat['with_params']}，含摘要 {kstat['with_summary']}）")
        for f in (k_json, k_csv):
            print(f"    + {f.name:<40} {f.stat().st_size/1024:9.1f} KB")

        # ── 题目 ──
        q_json = out_dir / "quiz" / f"{lib}.quiz_questions.json"
        write_json(q_json, {
            "schema_version": SCHEMA_VERSION,
            "exported_at": exported_at,
            "source_library": lib,
            "source_file": f"backend/data/users/{lib}.db",
            "notice": "node_id 对应同库 knowledge_nodes 的 id，请勿重编号。"
                      "payload 为题目 v2.0 契约对象（含 generation_meta 生成审计）。",
            "count": len(quizzes),
            "questions": quizzes,
        })
        q_csv = out_dir / "quiz" / f"{lib}.quiz_questions.csv"
        write_csv(q_csv, [question_csv_row(q) for q in quizzes], [
            "id", "node_id", "node_name", "subject_name", "qtype", "difficulty",
            "points", "ladder_steps", "correct_answer", "question", "options",
            "explanation", "generated_by",
        ])
        print(f"  题目 {len(quizzes)} 条  题型 {qstat['qtypes']}")
        if qstat["orphan_node"]:
            print(f"    ⚠️ 有 {qstat['orphan_node']} 条题目的 node_id 找不到对应知识点"
                  f"（库里原有，非本次导出造成）")
        for f in (q_json, q_csv):
            print(f"    + {f.name:<40} {f.stat().st_size/1024:9.1f} KB")

        summary.append({"lib": lib, "nodes": len(nodes), "quiz": len(quizzes),
                        "params": kstat["with_params"], "qtypes": qstat["qtypes"]})

    # ── 总清单 ──
    total_nodes = sum(s["nodes"] for s in summary)
    total_quiz = sum(s["quiz"] for s in summary)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at,
        "libraries": summary,
        "total_knowledge_nodes": total_nodes,
        "total_quiz_questions": total_quiz,
        "note": "各库 id 空间独立，不可跨库按 id 关联。",
    }
    m_path = out_dir / "manifest.json"
    write_json(m_path, manifest)

    total_bytes = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    print(f"\n{'='*66}")
    print(f"合计：知识点 {total_nodes} 条，题目 {total_quiz} 条，"
          f"共 {total_bytes/1024/1024:.2f} MB")
    print(f"输出：{out_dir}")
    print(f"{'='*66}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
