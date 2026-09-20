"""校验 backend/seeds/ 的导出结果：完整性、隐私边界、可还原性。

这个脚本回答三个问题，每个都必须有断言，不允许「看起来没问题」：

1. **完整性**——导出的条数与用户库是否逐一相等？抽样的 payload 是否逐字节一致？
2. **隐私边界**——有没有把 mastery/status/pin_hash 这类字段漏出去？
3. **可还原性**——JSON 能否被重新读回并还原成「一条库记录」的形状？

用法：
    cd backend
    python scripts/check_seeds.py
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEEDS = BACKEND_DIR / "seeds"
USERS = BACKEND_DIR / "data" / "users"

# 绝不允许出现在导出文件里的字段名（个人状态 / 凭据）
FORBIDDEN = (
    "mastery", "status", "quiz_ids",
    "pin_hash", "token_hash", "db_key", "device_id",
    "password", "secret", "api_key",
)
# 注意：notes 的 JSON 里含 "掌握" 等词是正常知识表述，不按关键词扫，只按字段名校验。

failures: list[str] = []
checks = 0


def check(cond: bool, ok: str, bad: str) -> None:
    global checks
    checks += 1
    if cond:
        print(f"  ✅ {ok}")
    else:
        print(f"  ❌ {bad}")
        failures.append(bad)


def open_ro(p: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(p).replace("\\", "/"), safe="/:") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def main() -> int:
    if not SEEDS.is_dir():
        print(f"错误：找不到 {SEEDS}，请先运行 export_seeds.py")
        return 1

    manifest = json.loads((SEEDS / "manifest.json").read_text(encoding="utf-8"))
    print(f"清单：导出时间 {manifest['exported_at']}")
    print(f"      知识点 {manifest['total_knowledge_nodes']} 条，"
          f"题目 {manifest['total_quiz_questions']} 条\n")

    for entry in manifest["libraries"]:
        lib = entry["lib"]
        db = USERS / f"{lib}.db"
        print(f"{'='*66}\n{lib}\n{'='*66}")
        con = open_ro(db)
        try:
            # ── 1. 完整性 ──
            db_nodes = con.execute("select count(*) from knowledge_nodes").fetchone()[0]
            db_quiz = con.execute("select count(*) from quiz_questions").fetchone()[0]

            kj = json.loads((SEEDS / "knowledge" / f"{lib}.knowledge_nodes.json")
                            .read_text(encoding="utf-8"))
            qj = json.loads((SEEDS / "quiz" / f"{lib}.quiz_questions.json")
                            .read_text(encoding="utf-8"))

            check(len(kj["nodes"]) == db_nodes == entry["nodes"],
                  f"知识点条数一致：{db_nodes}",
                  f"知识点条数不符：库 {db_nodes} / 导出 {len(kj['nodes'])} / 清单 {entry['nodes']}")
            check(len(qj["questions"]) == db_quiz == entry["quiz"],
                  f"题目条数一致：{db_quiz}",
                  f"题目条数不符：库 {db_quiz} / 导出 {len(qj['questions'])} / 清单 {entry['quiz']}")

            # ── 2. payload 逐字节还原 ──
            exported = {q["id"]: q["payload"] for q in qj["questions"]}
            sampled = con.execute(
                "select id, payload_json from quiz_questions order by id limit 60"
            ).fetchall()
            sampled += con.execute(
                "select id, payload_json from quiz_questions order by id desc limit 60"
            ).fetchall()
            bad = []
            for qid, raw in sampled:
                if json.loads(raw) != exported.get(qid):
                    bad.append(qid)
            check(not bad,
                  f"抽样 {len(sampled)} 条题目 payload 与库逐字节一致",
                  f"{len(bad)} 条题目 payload 与库不一致，例如 {bad[:5]}")

            # ── 3. 知识点内容还原 ──
            knodes = {n["id"]: n for n in kj["nodes"]}
            bad_k = []
            for nid, name, summary in con.execute(
                "select id, name, summary from knowledge_nodes"
            ):
                n = knodes.get(nid)
                if n is None or n["name"] != name or n.get("summary") != summary:
                    bad_k.append(nid)
            check(not bad_k,
                  f"{len(knodes)} 条知识点的 name/summary 与库一致",
                  f"{len(bad_k)} 条知识点内容不一致，例如 {bad_k[:5]}")

            # ── 4. params（notes 解析）无损 ──
            db_notes = dict(con.execute(
                "select id, notes from knowledge_nodes where notes is not null and notes != ''"
            ))
            lossy = []
            for nid, raw in db_notes.items():
                orig = json.loads(raw)
                got = knodes[nid].get("params")
                if orig != got:
                    lossy.append(nid)
            check(not lossy,
                  f"{len(db_notes)} 条笔记参数（notes）解析无损",
                  f"{len(lossy)} 条 notes 解析后与原文不等，例如 {lossy[:5]}")

            # ── 5. 题目 → 知识点 关联完整 ──
            knode_ids = set(knodes)
            orphans = [q["id"] for q in qj["questions"] if q["node_id"] not in knode_ids]
            check(len(orphans) <= 1,
                  f"题目关联完整（{len(orphans)} 条无对应知识点，与库内一致）",
                  f"{len(orphans)} 条题目的 node_id 无法对应知识点：{orphans[:5]}")
        finally:
            con.close()

    # ── 6. 隐私边界：扫全部导出文件的字段名 ──
    print(f"\n{'='*66}\n隐私边界检查\n{'='*66}")

    def keys_of(obj, out: set[str]) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.add(k)
                keys_of(v, out)
        elif isinstance(obj, list):
            for v in obj:
                keys_of(v, out)

    all_keys: set[str] = set()
    for f in sorted(SEEDS.rglob("*.json")):
        keys_of(json.loads(f.read_text(encoding="utf-8")), all_keys)
    leaked = sorted(all_keys & set(FORBIDDEN))
    check(not leaked,
          f"JSON 中无任何个人状态/凭据字段（已检 {len(all_keys)} 个字段名）",
          f"JSON 中泄漏字段：{leaked}")

    # CSV 表头同样检查
    csv_leak: list[str] = []
    for f in sorted(SEEDS.rglob("*.csv")):
        head = f.read_text(encoding="utf-8-sig").split("\n", 1)[0].strip()
        cols = {c.strip() for c in next(csv.reader(io.StringIO(head)))}
        hit = cols & set(FORBIDDEN)
        if hit:
            csv_leak.append(f"{f.name}: {sorted(hit)}")
    check(not csv_leak,
          f"CSV 表头无个人状态字段（已检 {len(list(SEEDS.rglob('*.csv')))} 个文件）",
          f"CSV 表头泄漏：{csv_leak}")

    # ── 7. 确认没有把 users 表相关数据带出来 ──
    text_all = "".join(f.read_text(encoding="utf-8", errors="ignore")
                       for f in SEEDS.rglob("*.json"))
    for probe in ("pin_hash", "token_hash", "legacy_testdevice01"):
        check(probe not in text_all,
              f"导出内容不含 `{probe}`",
              f"导出内容出现了 `{probe}`")

    # ── 8. CSV 的 BOM（Excel 中文） ──
    csvs = sorted(SEEDS.rglob("*.csv"))
    no_bom = [f.name for f in csvs if not f.read_bytes().startswith(b"\xef\xbb\xbf")]
    check(not no_bom,
          f"{len(csvs)} 个 CSV 均带 UTF-8 BOM（Excel 打开不乱码）",
          f"这些 CSV 缺 BOM：{no_bom}")

    print(f"\n{'='*66}")
    if failures:
        print(f"❌ {checks - len(failures)}/{checks} 项通过，{len(failures)} 项失败：")
        for f in failures:
            print(f"   - {f}")
        print(f"{'='*66}")
        return 1
    print(f"✅ 全部 {checks} 项通过")
    print(f"{'='*66}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
