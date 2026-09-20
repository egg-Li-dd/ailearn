"""错题闭环服务（Phase 5）。

功能：
1. 错题本管理：基于 QuizAnswer.score < 60 自动收录错题
2. 错题统计：总错题数、高频错题、薄弱知识点、错误趋势
3. 针对性复习推荐：基于薄弱点推荐知识点和题目
4. 错题重练：从错题中随机抽题生成练习
5. 错题本导出：CSV 格式导出

设计要点：
- 不新增数据库表，复用 QuizAnswer（score<60 即错题）
- 错题去重：同一题目多次答错只算一道错题，但记录错误次数
- 针对性复习结合 Phase 3 的薄弱点诊断和知识图谱
- 导出格式兼容 Excel 直接打开
"""
import csv
import io
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, QuizQuestion, QuizAnswer, Course

logger = logging.getLogger("ailearn.wrong_book")

# 错题阈值：得分低于此值视为答错
WRONG_THRESHOLD = 60


# ============================================================
# 核心查询函数
# ============================================================

def get_wrong_answers(
    db: Session,
    *,
    subject_id: int | None = None,
    node_id: int | None = None,
    days: int | None = None,
    min_wrong_count: int = 1,
) -> list[dict[str, Any]]:
    """获取错题列表（按题目去重，记录错误次数）。

    Args:
        db: 数据库会话
        subject_id: 按科目筛选
        node_id: 按知识点筛选
        days: 只看最近 N 天的错题
        min_wrong_count: 最低错误次数

    Returns:
        错题列表，每项包含题目信息、错误次数、最近错误时间、关联知识点
    """
    # 构建查询条件
    conditions = [QuizAnswer.score < WRONG_THRESHOLD]
    if days:
        since = datetime.utcnow() - timedelta(days=days)
        conditions.append(QuizAnswer.created_at >= since)

    # 查询所有错题答题记录
    query = select(QuizAnswer).where(and_(*conditions)).order_by(QuizAnswer.created_at.desc())
    answers = db.execute(query).scalars().all()

    # 按题目去重聚合
    wrong_map: dict[int, dict[str, Any]] = {}
    for ans in answers:
        qid = ans.question_id
        if qid not in wrong_map:
            question = db.get(QuizQuestion, qid)
            if not question:
                continue
            # 解析题目 payload
            try:
                payload = json.loads(question.payload_json)
            except (json.JSONDecodeError, TypeError):
                payload = {}

            # 规范化 analysis 字段（兼容字符串和数组）
            analysis_data = payload.get("analysis", [])
            if isinstance(analysis_data, str):
                analysis_data = [{"step": 1, "text": analysis_data}] if analysis_data else []
            elif not isinstance(analysis_data, list):
                analysis_data = []

            # 获取关联知识点
            node = None
            if question.node_id:
                node = db.get(KnowledgeNode, question.node_id)

            # 科目筛选
            if subject_id and node and node.subject_id != subject_id:
                continue
            if node_id and question.node_id != node_id:
                continue

            wrong_map[qid] = {
                "question_id": qid,
                "question": payload.get("question", ""),
                "qtype": question.qtype,
                "difficulty": question.difficulty,
                "options": payload.get("options"),
                "correct_answer": payload.get("correct_answer"),
                "analysis": analysis_data,
                "thought_map": payload.get("thought_map", ""),
                "error_tips": payload.get("error_tips", ""),
                "node_id": question.node_id,
                "node_name": node.name if node else None,
                "subject_id": node.subject_id if node else None,
                "wrong_count": 0,
                "last_wrong_at": None,
                "wrong_answers": [],  # 最近几次错误答案
            }

        if qid in wrong_map:
            wrong_map[qid]["wrong_count"] += 1
            if wrong_map[qid]["last_wrong_at"] is None or ans.created_at > wrong_map[qid]["last_wrong_at"]:
                wrong_map[qid]["last_wrong_at"] = ans.created_at.isoformat() if ans.created_at else None
            # 记录最近3次错误答案
            if len(wrong_map[qid]["wrong_answers"]) < 3:
                wrong_map[qid]["wrong_answers"].append({
                    "user_answer": ans.user_answer,
                    "score": ans.score,
                    "created_at": ans.created_at.isoformat() if ans.created_at else None,
                })

    # 按错误次数筛选和排序
    result = [w for w in wrong_map.values() if w["wrong_count"] >= min_wrong_count]
    result.sort(key=lambda x: (x["wrong_count"], x["last_wrong_at"] or ""), reverse=True)
    return result


def get_wrong_stats(db: Session, *, subject_id: int | None = None, days: int | None = None) -> dict[str, Any]:
    """获取错题统计数据。

    Returns:
        {
            "total_wrong": int,           # 错题总数（去重后）
            "total_wrong_attempts": int,  # 错误答题总次数
            "high_frequency": list,        # 高频错题（错误次数>=2）
            "weak_nodes": list,            # 薄弱知识点（错题数排名）
            "by_difficulty": dict,         # 按难度分布
            "by_qtype": dict,              # 按题型分布
            "trend": list,                 # 最近7天错误趋势
        }
    """
    wrong_list = get_wrong_answers(db, subject_id=subject_id, days=days)

    total_wrong = len(wrong_list)
    total_wrong_attempts = sum(w["wrong_count"] for w in wrong_list)

    # 高频错题（错误次数>=2）
    high_frequency = [w for w in wrong_list if w["wrong_count"] >= 2][:10]

    # 薄弱知识点（按错题数排名）
    node_stats: dict[int, dict[str, Any]] = {}
    for w in wrong_list:
        nid = w.get("node_id")
        if nid:
            if nid not in node_stats:
                node_stats[nid] = {
                    "node_id": nid,
                    "node_name": w.get("node_name"),
                    "wrong_count": 0,
                    "question_count": 0,
                }
            node_stats[nid]["wrong_count"] += w["wrong_count"]
            node_stats[nid]["question_count"] += 1
    weak_nodes = sorted(node_stats.values(), key=lambda x: x["wrong_count"], reverse=True)[:10]

    # 按难度分布
    by_difficulty = {}
    for w in wrong_list:
        d = w.get("difficulty", 1)
        by_difficulty[d] = by_difficulty.get(d, 0) + 1

    # 按题型分布
    by_qtype = {}
    for w in wrong_list:
        t = w.get("qtype", "unknown")
        by_qtype[t] = by_qtype.get(t, 0) + 1

    # 最近7天错误趋势
    trend = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = db.execute(
            select(func.count(QuizAnswer.id)).where(
                QuizAnswer.score < WRONG_THRESHOLD,
                QuizAnswer.created_at >= day_start,
                QuizAnswer.created_at < day_end,
            )
        ).scalar()
        trend.append({
            "date": day.strftime("%m-%d"),
            "wrong_count": count or 0,
        })

    return {
        "total_wrong": total_wrong,
        "total_wrong_attempts": total_wrong_attempts,
        "high_frequency": high_frequency,
        "weak_nodes": weak_nodes,
        "by_difficulty": by_difficulty,
        "by_qtype": by_qtype,
        "trend": trend,
    }


def get_review_recommendations(
    db: Session,
    *,
    subject_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """获取针对性复习推荐。

    基于：
    1. 错题最多的知识点（优先复习）
    2. 掌握度低的知识点（结合 Phase 3）
    3. 最近答错的题目（近期复习）
    4. 高频错题（重点突破）

    Returns:
        {
            "priority_nodes": list,    # 优先复习的知识点
            "recent_wrong": list,      # 最近答错的题目
            "high_frequency": list,    # 高频错题
            "review_plan": list,       # 复习计划建议
        }
    """
    stats = get_wrong_stats(db, subject_id=subject_id)
    wrong_list = get_wrong_answers(db, subject_id=subject_id)

    # 优先复习知识点（错题最多的前5个）
    priority_nodes = stats["weak_nodes"][:5]

    # 补充掌握度信息
    for pn in priority_nodes:
        node = db.get(KnowledgeNode, pn["node_id"])
        if node:
            pn["mastery"] = node.mastery
            pn["difficulty"] = node.difficulty
            pn["summary"] = node.summary

    # 最近答错的题目（最近3天，前5道）
    recent_wrong = [w for w in wrong_list if w.get("last_wrong_at")][:5]

    # 高频错题（前5道）
    high_frequency = stats["high_frequency"][:5]

    # 生成复习计划建议
    review_plan = []
    if priority_nodes:
        review_plan.append({
            "priority": 1,
            "type": "知识点复习",
            "content": f"重点复习 {priority_nodes[0]['node_name']}（错题{int(priority_nodes[0]['wrong_count'])}次）",
            "action": "查看知识图谱，梳理该知识点的前置依赖和核心概念",
        })
    if len(priority_nodes) > 1:
        review_plan.append({
            "priority": 2,
            "type": "知识点复习",
            "content": f"巩固 {priority_nodes[1]['node_name']}（错题{int(priority_nodes[1]['wrong_count'])}次）",
            "action": "重做该知识点下的错题，结合AI解析理解错误原因",
        })
    if high_frequency:
        review_plan.append({
            "priority": 3,
            "type": "错题重练",
            "content": f"高频错题突破：{high_frequency[0]['question'][:50]}...（答错{int(high_frequency[0]['wrong_count'])}次）",
            "action": "使用错题重练功能，反复练习直到连续答对",
        })
    review_plan.append({
        "priority": 4,
        "type": "日常巩固",
        "content": "每天从错题本中随机抽5题重练",
        "action": "使用错题重练功能，保持错题敏感度",
    })

    return {
        "priority_nodes": priority_nodes,
        "recent_wrong": recent_wrong,
        "high_frequency": high_frequency,
        "review_plan": review_plan[:limit],
    }


def generate_practice(
    db: Session,
    *,
    subject_id: int | None = None,
    node_id: int | None = None,
    count: int = 5,
    mode: str = "random",
) -> dict[str, Any]:
    """生成错题重练题目。

    Args:
        db: 数据库会话
        subject_id: 按科目筛选
        node_id: 按知识点筛选
        count: 题目数量
        mode: 出题模式
            - random: 随机抽取
            - frequent: 优先高频错题
            - recent: 优先最近答错

    Returns:
        {
            "total": int,
            "questions": list,
            "mode": str,
        }
    """
    wrong_list = get_wrong_answers(db, subject_id=subject_id, node_id=node_id)

    if not wrong_list:
        return {"total": 0, "questions": [], "mode": mode, "message": "暂无错题"}

    # 按模式排序
    if mode == "frequent":
        wrong_list.sort(key=lambda x: x["wrong_count"], reverse=True)
    elif mode == "recent":
        wrong_list.sort(key=lambda x: x.get("last_wrong_at") or "", reverse=True)
    else:  # random
        random.shuffle(wrong_list)

    # 取前 count 道
    selected = wrong_list[:count]

    # 构建题目数据（去掉答案和解析，留待作答后显示）
    questions = []
    for w in selected:
        questions.append({
            "question_id": w["question_id"],
            "question": w["question"],
            "qtype": w["qtype"],
            "difficulty": w["difficulty"],
            "options": w["options"],
            "node_id": w["node_id"],
            "node_name": w["node_name"],
            "wrong_count": w["wrong_count"],
            "last_wrong_at": w.get("last_wrong_at"),
            # 答案和解析放在作答后显示的字段
            "_correct_answer": w["correct_answer"],
            "_analysis": w["analysis"],
            "_thought_map": w["thought_map"],
            "_error_tips": w["error_tips"],
        })

    return {
        "total": len(questions),
        "questions": questions,
        "mode": mode,
        "available": len(wrong_list),
    }


def export_wrong_book(
    db: Session,
    *,
    subject_id: int | None = None,
    format: str = "csv",
) -> dict[str, Any]:
    """导出错题本。

    Args:
        db: 数据库会话
        subject_id: 按科目筛选
        format: 导出格式（csv / json）

    Returns:
        {
            "format": str,
            "count": int,
            "content": str,  # CSV 文本或 JSON 字符串
            "filename": str,
        }
    """
    wrong_list = get_wrong_answers(db, subject_id=subject_id)

    if format == "json":
        return {
            "format": "json",
            "count": len(wrong_list),
            "content": json.dumps(wrong_list, ensure_ascii=False, indent=2),
            "filename": f"错题本_{datetime.now().strftime('%Y%m%d')}.json",
        }

    # CSV 格式
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "序号", "题目", "题型", "难度", "正确答案",
        "关联知识点", "错误次数", "最近错误时间",
        "解析", "思路要点", "易错点",
    ])

    qtype_map = {
        "single_choice": "单选题", "multiple_choice": "多选题",
        "judge": "判断题", "fill_single": "填空题",
        "fill_cloze": "填空题", "short": "简答题",
        "code": "代码题", "recite": "背诵题",
    }

    for i, w in enumerate(wrong_list, 1):
        # 解析步骤合并为文本（兼容字符串和数组两种格式）
        analysis_text = ""
        analysis_data = w.get("analysis", [])
        if isinstance(analysis_data, list) and analysis_data:
            analysis_text = "\n".join([
                f"步骤{a.get('step', j+1) if isinstance(a, dict) else j+1}: "
                f"{a.get('text', '') if isinstance(a, dict) else str(a)}"
                for j, a in enumerate(analysis_data)
            ])
        elif isinstance(analysis_data, str) and analysis_data:
            analysis_text = analysis_data

        # 选项附加到题目后
        question_text = w["question"]
        if w.get("options"):
            opt_str = "\n".join([f"{chr(65+j)}. {opt}" for j, opt in enumerate(w["options"])])
            question_text += f"\n{opt_str}"

        writer.writerow([
            i,
            question_text,
            qtype_map.get(w["qtype"], w["qtype"]),
            w["difficulty"],
            w.get("correct_answer", ""),
            w.get("node_name", ""),
            w["wrong_count"],
            w.get("last_wrong_at", ""),
            analysis_text,
            w.get("thought_map", ""),
            w.get("error_tips", ""),
        ])

    return {
        "format": "csv",
        "count": len(wrong_list),
        "content": output.getvalue(),
        "filename": f"错题本_{datetime.now().strftime('%Y%m%d')}.csv",
    }
