"""知识点关联增强服务（Phase 3）。

功能：
1. 前置依赖分析：AI 分析知识点间的前置依赖关系，填充 prerequisites 字段
2. 笔记生成：AI 为知识点生成详细笔记（核心概念/公式/题型/方法/易错点），填充 notes 字段
3. 跨章节关联发现：发现不同章节知识点间的联系
4. 薄弱点诊断：基于掌握度和题目数据定位薄弱知识点

设计要点：
- 批量分析：一次 AI 调用分析一个章节的所有知识点，减少调用次数
- 按需生成：笔记可单个生成，也可批量生成
- 用 Function Calling 保证结构化输出
"""
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import KnowledgeNode, QuizQuestion, QuizAnswer
from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_with_tools, extract_tool_arguments

logger = logging.getLogger("ailearn.knowledge_enhancer")


# ============================================================
# Prompt 模板
# ============================================================

_PREREQ_SYSTEM_PROMPT = """你是一个计算机考研知识体系专家，擅长分析知识点之间的前置依赖关系。

## 任务
给定一个章节下的所有知识点列表（含名称和简要说明），分析每个知识点的前置依赖——即学习这个知识点之前必须先掌握哪些其他知识点。

## 分析原则
1. 前置依赖必须是同一章节下的知识点（用 index 引用）
2. 依赖关系是直接的，不要传递依赖（如 A 依赖 B，B 依赖 C，则 A 的直接依赖只有 B）
3. 如果某个知识点是基础概念，没有前置依赖，则返回空数组
4. 依赖关系要符合学习逻辑：先基础后应用，先概念后计算

## 输出要求
必须调用 analyze_prerequisites 函数返回结构化数据。
"""


_NOTES_SYSTEM_PROMPT = """你是一个计算机考研资深辅导老师，擅长为知识点生成高质量的学习笔记。

## 笔记结构
为每个知识点生成以下内容：
1. core_concept：核心概念（用1-2句话精准定义）
2. key_formulas：关键公式/定理/性质（数组，每条一行，用LaTeX）
3. common_question_types：常见题型（数组，3-5种典型考法）
4. solution_methods：解题方法/步骤（数组，每种方法简要说明）
5. error_points：易错点/陷阱（数组，2-4个常见错误）
6. memory_tips：记忆技巧/口诀（可选，1句话）

## 要求
- 内容要精准、简洁，符合考研408考纲
- 公式用 LaTeX 格式（$...$ 行内，$$...$$ 独立）
- 不要泛泛而谈，要具体到这个知识点
- 如果知识点是纯概念性的，key_formulas 可以为空数组

## 输出要求
必须调用 generate_notes 函数返回结构化数据。
"""


# ============================================================
# Function Definitions
# ============================================================

_PREREQ_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "analyze_prerequisites",
        "description": "分析知识点的前置依赖关系",
        "parameters": {
            "type": "object",
            "properties": {
                "prerequisites": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer", "description": "知识点在列表中的索引（从0开始）"},
                            "prereq_indices": {"type": "array", "items": {"type": "integer"}, "description": "前置依赖知识点的索引数组"},
                            "reason": {"type": "string", "description": "依赖关系的简要说明"},
                        },
                        "required": ["index", "prereq_indices", "reason"],
                    },
                    "description": "每个知识点的前置依赖分析结果",
                }
            },
            "required": ["prerequisites"],
        },
    },
}


_NOTES_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "generate_notes",
        "description": "为知识点生成详细学习笔记",
        "parameters": {
            "type": "object",
            "properties": {
                "core_concept": {"type": "string", "description": "核心概念定义"},
                "key_formulas": {"type": "array", "items": {"type": "string"}, "description": "关键公式/定理列表"},
                "common_question_types": {"type": "array", "items": {"type": "string"}, "description": "常见题型列表"},
                "solution_methods": {"type": "array", "items": {"type": "string"}, "description": "解题方法列表"},
                "error_points": {"type": "array", "items": {"type": "string"}, "description": "易错点列表"},
                "memory_tips": {"type": "string", "description": "记忆技巧（可选）"},
            },
            "required": ["core_concept", "key_formulas", "common_question_types", "solution_methods", "error_points"],
        },
    },
}


# ============================================================
# 核心函数
# ============================================================

def get_chapter_nodes(db: Session, chapter_node_id: int) -> list[KnowledgeNode]:
    """获取章节下所有知识点节点（level=4）。"""
    sections = db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.parent_id == chapter_node_id,
            KnowledgeNode.level == 3,
        )
    ).scalars().all()
    section_ids = [s.id for s in sections]
    if not section_ids:
        return []
    points = db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.parent_id.in_(section_ids),
            KnowledgeNode.level == 4,
        ).order_by(KnowledgeNode.sort, KnowledgeNode.id)
    ).scalars().all()
    return list(points)


async def analyze_prerequisites_for_chapter(
    db: Session,
    chapter_node_id: int,
    *,
    auto_apply: bool = True,
) -> dict[str, Any]:
    """分析一个章节下所有知识点的前置依赖关系。

    Args:
        db: 数据库会话
        chapter_node_id: 章节节点 ID（level=2）
        auto_apply: 是否自动将结果写入数据库

    Returns:
        {
            "chapter_id": int,
            "chapter_name": str,
            "nodes": list,
            "prerequisites": list,  # 分析结果
            "applied": bool,
        }
    """
    chapter = db.get(KnowledgeNode, chapter_node_id)
    if not chapter:
        raise ValueError(f"章节节点不存在: {chapter_node_id}")

    nodes = get_chapter_nodes(db, chapter_node_id)
    if not nodes:
        raise ValueError(f"章节 {chapter.name} 下没有知识点节点")

    logger.info("分析章节 '%s' 的前置依赖：%d 个知识点", chapter.name, len(nodes))

    # 构建知识点列表
    node_list = []
    for i, node in enumerate(nodes):
        node_list.append({
            "index": i,
            "id": node.id,
            "name": node.name,
            "summary": node.summary or "",
        })

    # 构建 user prompt
    nodes_text = "\n".join([
        f"[{n['index']}] {n['name']}" + (f"：{n['summary']}" if n['summary'] else "")
        for n in node_list
    ])
    user_prompt = f"章节：{chapter.name}\n\n知识点列表：\n{nodes_text}\n\n请分析每个知识点的前置依赖关系。"

    messages = [
        {"role": "system", "content": _PREREQ_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        set_function_type("knowledge")
        result = await chat_with_tools(
            messages,
            tools=[_PREREQ_TOOL_DEF],
            tool_choice={"type": "function", "function": {"name": "analyze_prerequisites"}},
            temperature=0.2,
            db=db,
        )
    except AiGatewayError as e:
        logger.error("前置依赖分析失败: %s", e)
        raise

    analysis = extract_tool_arguments(result)
    if not analysis:
        raise AiGatewayError("前置依赖分析失败：未返回结构化数据")

    prereq_list = analysis.get("prerequisites", [])

    # 自动应用结果
    applied = False
    if auto_apply:
        for item in prereq_list:
            idx = item.get("index")
            prereq_indices = item.get("prereq_indices", [])
            if idx is not None and 0 <= idx < len(nodes):
                node = nodes[idx]
                # 转换为知识点 ID 列表
                prereq_ids = [nodes[i].id for i in prereq_indices if 0 <= i < len(nodes)]
                node.prerequisites = json.dumps(prereq_ids, ensure_ascii=False) if prereq_ids else None
        db.commit()
        applied = True
        logger.info("前置依赖分析已应用到 %d 个知识点", len(prereq_list))

    return {
        "chapter_id": chapter.id,
        "chapter_name": chapter.name,
        "nodes": node_list,
        "prerequisites": prereq_list,
        "applied": applied,
    }


async def generate_notes_for_node(
    db: Session,
    node_id: int,
    *,
    auto_apply: bool = True,
) -> dict[str, Any]:
    """为单个知识点生成详细笔记。

    Args:
        db: 数据库会话
        node_id: 知识点节点 ID
        auto_apply: 是否自动写入 notes 字段

    Returns:
        笔记数据
    """
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")

    logger.info("为知识点 '%s' 生成笔记", node.name)

    # 获取父节点信息（章节、小节），提供上下文
    context_parts = [f"知识点：{node.name}"]
    if node.summary:
        context_parts.append(f"简要说明：{node.summary}")
    if node.parent_id:
        parent = db.get(KnowledgeNode, node.parent_id)
        if parent:
            context_parts.append(f"所属小节：{parent.name}")
            if parent.parent_id:
                grandparent = db.get(KnowledgeNode, parent.parent_id)
                if grandparent:
                    context_parts.append(f"所属章节：{grandparent.name}")

    user_prompt = "\n".join(context_parts) + "\n\n请为这个知识点生成详细的学习笔记。"

    messages = [
        {"role": "system", "content": _NOTES_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        set_function_type("knowledge")
        result = await chat_with_tools(
            messages,
            tools=[_NOTES_TOOL_DEF],
            tool_choice={"type": "function", "function": {"name": "generate_notes"}},
            temperature=0.4,
            db=db,
        )
    except AiGatewayError as e:
        logger.error("笔记生成失败: %s", e)
        raise

    notes = extract_tool_arguments(result)
    if not notes:
        raise AiGatewayError("笔记生成失败：未返回结构化数据")

    # 自动应用
    if auto_apply:
        notes["generated_at"] = datetime.utcnow().isoformat()
        node.notes = json.dumps(notes, ensure_ascii=False)
        db.commit()
        logger.info("笔记已保存到知识点 '%s'", node.name)

    return notes


async def generate_notes_batch(
    db: Session,
    node_ids: list[int],
    *,
    auto_apply: bool = True,
    max_batch: int = 50,
) -> dict[str, Any]:
    """批量为知识点生成笔记。

    Args:
        db: 数据库会话
        node_ids: 知识点 ID 列表（最多 max_batch 个）
        auto_apply: 是否自动写入
        max_batch: 单次批量上限，默认50

    Returns:
        {
            "total": int,
            "success": int,
            "failed": int,
            "results": list,
            "failures": list,
            "truncated": bool,  # 是否因超过上限被截断
        }
    """
    truncated = False
    if len(node_ids) > max_batch:
        logger.warning("批量笔记生成请求 %d 个节点，超过上限 %d，已截断", len(node_ids), max_batch)
        node_ids = node_ids[:max_batch]
        truncated = True

    results = []
    failures = []
    success_count = 0

    for i, node_id in enumerate(node_ids):
        logger.info("批量生成笔记进度: %d/%d", i + 1, len(node_ids))
        try:
            notes = await generate_notes_for_node(db, node_id, auto_apply=auto_apply)
            results.append({"node_id": node_id, "notes": notes})
            success_count += 1
        except Exception as e:
            logger.warning("笔记生成失败 node=%d: %s", node_id, e)
            failures.append({"node_id": node_id, "error": str(e)})

    return {
        "total": len(node_ids),
        "success": success_count,
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "truncated": truncated,
    }


def diagnose_weak_points(db: Session, subject_id: int) -> list[dict[str, Any]]:
    """诊断科目下的薄弱知识点。

    基于：
    - 掌握度（mastery < 60）
    - 关联题目的平均得分
    - 错题数量

    性能优化：用 JOIN 一次性获取所有题目和答案，避免 N+1 查询。
    """
    # 获取科目下所有 level=4 知识点
    nodes = db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.subject_id == subject_id,
            KnowledgeNode.level == 4,
        )
    ).scalars().all()

    node_ids = [n.id for n in nodes]
    if not node_ids:
        return []

    # 一次性查询所有关联题目
    questions = db.execute(
        select(QuizQuestion).where(QuizQuestion.node_id.in_(node_ids))
    ).scalars().all()

    question_ids = [q.id for q in questions]
    q_by_node: dict[int, list[QuizQuestion]] = {}
    for q in questions:
        q_by_node.setdefault(q.node_id, []).append(q)

    # 一次性查询所有答案（如果有题目）
    answers_by_question: dict[int, list[QuizAnswer]] = {}
    if question_ids:
        answers = db.execute(
            select(QuizAnswer).where(QuizAnswer.question_id.in_(question_ids))
        ).scalars().all()
        for a in answers:
            answers_by_question.setdefault(a.question_id, []).append(a)

    weak_points = []
    for node in nodes:
        # 基础薄弱分：掌握度越低越薄弱
        weakness_score = max(0, 100 - node.mastery)

        # 统计该知识点的答题情况（从预加载的数据中取）
        node_questions = q_by_node.get(node.id, [])
        total_answers = 0
        total_score = 0
        wrong_count = 0

        for q in node_questions:
            q_answers = answers_by_question.get(q.id, [])
            for a in q_answers:
                total_answers += 1
                if a.score is not None:
                    total_score += a.score
                    if a.score < 60:
                        wrong_count += 1

        avg_score = total_score / total_answers if total_answers > 0 else None

        # 有答题数据时，结合正确率调整薄弱分
        if total_answers > 0 and avg_score is not None:
            weakness_score = weakness_score * 0.5 + (100 - avg_score) * 0.5

        # 只有掌握度低或有错题的才计入
        if node.mastery < 60 or wrong_count > 0:
            weak_points.append({
                "node_id": node.id,
                "name": node.name,
                "mastery": node.mastery,
                "question_count": len(node_questions),
                "answer_count": total_answers,
                "avg_score": round(avg_score, 1) if avg_score is not None else None,
                "wrong_count": wrong_count,
                "weakness_score": round(weakness_score, 1),
                "level": "high" if weakness_score >= 60 else "medium" if weakness_score >= 40 else "low",
            })

    # 按薄弱程度排序
    weak_points.sort(key=lambda x: x["weakness_score"], reverse=True)
    return weak_points


def get_knowledge_graph(db: Session, subject_id: int) -> dict[str, Any]:
    """获取科目的知识图谱数据（用于前端可视化）。

    返回节点和边：
    - nodes: 知识点节点（含名称、掌握度、层级）
    - edges: 前置依赖关系边

    Args:
        db: 数据库会话
        subject_id: 科目 ID

    Returns:
        {
            "nodes": list,
            "edges": list,
            "stats": dict,
        }
    """
    # 获取科目下所有节点
    all_nodes = db.execute(
        select(KnowledgeNode).where(KnowledgeNode.subject_id == subject_id)
    ).scalars().all()

    nodes_by_id = {n.id: n for n in all_nodes}

    # 构建节点列表（主要展示 level=3 和 level=4）
    graph_nodes = []
    for node in all_nodes:
        if node.level >= 2:  # 章节及以下
            graph_nodes.append({
                "id": node.id,
                "name": node.name,
                "level": node.level,
                "mastery": node.mastery,
                "difficulty": node.difficulty,
                "parent_id": node.parent_id,
                "has_notes": bool(node.notes),
                "has_prerequisites": bool(node.prerequisites),
                "notes": node.notes,  # 完整笔记 JSON，前端详情面板用
                "prerequisites": node.prerequisites,  # 完整前置依赖 JSON
                "summary": node.summary,  # 节点摘要
            })

    # 构建边：层级关系 + 前置依赖关系
    edges = []
    edge_set = set()

    for node in all_nodes:
        # 层级边
        if node.parent_id and node.parent_id in nodes_by_id:
            edge_key = (node.parent_id, node.id, "hierarchy")
            if edge_key not in edge_set:
                edges.append({
                    "source": node.parent_id,
                    "target": node.id,
                    "type": "hierarchy",
                })
                edge_set.add(edge_key)

        # 前置依赖边
        if node.prerequisites:
            try:
                prereq_ids = json.loads(node.prerequisites)
                for pid in prereq_ids:
                    if pid in nodes_by_id:
                        edge_key = (pid, node.id, "prerequisite")
                        if edge_key not in edge_set:
                            edges.append({
                                "source": pid,
                                "target": node.id,
                                "type": "prerequisite",
                            })
                            edge_set.add(edge_key)
            except (json.JSONDecodeError, TypeError):
                pass

    # 统计
    stats = {
        "total_nodes": len(graph_nodes),
        "total_edges": len(edges),
        "hierarchy_edges": sum(1 for e in edges if e["type"] == "hierarchy"),
        "prerequisite_edges": sum(1 for e in edges if e["type"] == "prerequisite"),
        "nodes_with_notes": sum(1 for n in graph_nodes if n["has_notes"]),
        "nodes_with_prerequisites": sum(1 for n in graph_nodes if n["has_prerequisites"]),
        "avg_mastery": round(sum(n["mastery"] for n in graph_nodes) / len(graph_nodes), 1) if graph_nodes else 0,
    }

    return {
        "nodes": graph_nodes,
        "edges": edges,
        "stats": stats,
    }
