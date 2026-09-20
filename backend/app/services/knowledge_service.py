"""知识树服务：N+1 查询优化 + 审计日志辅助。"""
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import KnowledgeNode
from ..schemas.knowledge import NodeOut


def _question_count(node: KnowledgeNode) -> int:
    if not node.quiz_ids:
        return 0
    try:
        return len(json.loads(node.quiz_ids))
    except (json.JSONDecodeError, TypeError):
        return 0


def _node_to_dict(node: KnowledgeNode) -> dict:
    """将 ORM 对象转为字典（不含 children）。"""
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "subject_id": node.subject_id,
        "name": node.name,
        "level": node.level,
        "difficulty": node.difficulty,
        "mastery": node.mastery,
        "status": node.status,
        "source": node.source,
        "summary": node.summary,
        "sort": node.sort,
        "icon": node.icon,
        "notes": node.notes,
        "prerequisites": node.prerequisites,
        "question_count": _question_count(node),
        "children": [],
    }


def build_tree_efficient(
    db: Session,
    subject_id: int | None = None,
    search: str | None = None,
    mastery_min: int | None = None,
    mastery_max: int | None = None,
    max_level: int | None = None,
) -> list[NodeOut]:
    """
    高效构建知识树：一次性查询所有节点 + 内存建树，避免 N+1 查询。

    优化策略：
    1. 若指定 subject_id，用递归 CTE 获取该科目根节点及其所有子孙节点 ID
    2. 一次性 IN 查询所有节点
    3. 在内存中按 parent_id 构建树结构
    4. 搜索/掌握度/层级过滤在内存中完成
    """
    # Step 1: 确定需要查询的节点 ID 范围
    if subject_id is not None:
        # 递归 CTE：找到该科目的所有根节点，然后递归获取所有子孙
        cte_sql = text("""
            WITH RECURSIVE tree_ids AS (
                SELECT id FROM knowledge_nodes
                WHERE parent_id IS NULL AND subject_id = :sid
                UNION ALL
                SELECT kn.id FROM knowledge_nodes kn
                INNER JOIN tree_ids ti ON kn.parent_id = ti.id
            )
            SELECT id FROM tree_ids
        """)
        all_ids = [r[0] for r in db.execute(cte_sql, {"sid": subject_id}).fetchall()]
        if not all_ids:
            return []
        # 一次性查询所有节点
        nodes = list(db.scalars(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(all_ids))
        ))
    else:
        # 全量查询（数据量不大时可接受）
        nodes = list(db.scalars(select(KnowledgeNode)))

    # Step 2: 内存建树
    node_map = {n.id: _node_to_dict(n) for n in nodes}
    roots = []
    for n in nodes:
        d = node_map[n.id]
        if n.parent_id is None:
            roots.append(d)
        elif n.parent_id in node_map:
            node_map[n.parent_id]["children"].append(d)

    # 按 sort, id 排序所有层级
    def sort_children(node_list):
        for n in node_list:
            if n["children"]:
                n["children"].sort(key=lambda x: (x["sort"], x["id"]))
                sort_children(n["children"])
    roots.sort(key=lambda x: (x["sort"], x["id"]))
    sort_children(roots)

    # Step 3: 过滤
    result = roots

    # 搜索过滤：保留匹配节点及其所有祖先
    if search:
        q = search.lower()
        matched_ids = set()
        def collect_match(node):
            if q in node["name"].lower():
                matched_ids.add(node["id"])
            for c in node["children"]:
                collect_match(c)
        for r in result:
            collect_match(r)

        keep_ids = set(matched_ids)
        for nid in matched_ids:
            cur = node_map.get(nid)
            while cur and cur["parent_id"]:
                keep_ids.add(cur["parent_id"])
                cur = node_map.get(cur["parent_id"])

        def filter_search(node):
            if node["id"] not in keep_ids:
                return None
            node["children"] = [c for c in (filter_search(c) for c in node["children"]) if c]
            return node
        result = [r for r in (filter_search(r) for r in result) if r]

    # 掌握度过滤
    if mastery_min is not None or mastery_max is not None:
        def filter_mastery(node):
            if mastery_min is not None and node["mastery"] < mastery_min:
                return None
            if mastery_max is not None and node["mastery"] > mastery_max:
                return None
            node["children"] = [c for c in (filter_mastery(c) for c in node["children"]) if c]
            return node
        result = [r for r in (filter_mastery(r) for r in result) if r]

    # 最大层级过滤
    if max_level is not None:
        def filter_level(node):
            if node["level"] > max_level:
                return None
            node["children"] = [c for c in (filter_level(c) for c in node["children"]) if c]
            return node
        result = [r for r in (filter_level(r) for r in result) if r]

    # 转为 NodeOut 对象
    def to_node_out(d):
        return NodeOut(
            id=d["id"], parent_id=d["parent_id"], subject_id=d["subject_id"],
            name=d["name"], level=d["level"], difficulty=d["difficulty"],
            mastery=d["mastery"], status=d["status"], source=d["source"],
            summary=d["summary"], sort=d["sort"], icon=d["icon"], notes=d["notes"],
            prerequisites=d["prerequisites"], question_count=d["question_count"],
            children=[to_node_out(c) for c in d["children"]],
        )

    return [to_node_out(r) for r in result]


def get_single_node_tree(db: Session, node_id: int) -> NodeOut:
    """获取单个节点及其子树（用于节点详情/编辑后返回）。"""
    node = db.get(KnowledgeNode, node_id)
    if not node:
        return None
    # 递归获取该节点的所有子孙
    cte_sql = text("""
        WITH RECURSIVE tree_ids AS (
            SELECT id FROM knowledge_nodes WHERE id = :nid
            UNION ALL
            SELECT kn.id FROM knowledge_nodes kn
            INNER JOIN tree_ids ti ON kn.parent_id = ti.id
        )
        SELECT id FROM tree_ids
    """)
    all_ids = [r[0] for r in db.execute(cte_sql, {"nid": node_id}).fetchall()]
    nodes = list(db.scalars(select(KnowledgeNode).where(KnowledgeNode.id.in_(all_ids))))

    node_map = {n.id: _node_to_dict(n) for n in nodes}
    root = node_map[node_id]
    for n in nodes:
        if n.parent_id and n.parent_id in node_map and n.id != node_id:
            node_map[n.parent_id]["children"].append(node_map[n.id])

    def sort_children(node):
        node["children"].sort(key=lambda x: (x["sort"], x["id"]))
        for c in node["children"]:
            sort_children(c)
    sort_children(root)

    def to_node_out(d):
        return NodeOut(
            id=d["id"], parent_id=d["parent_id"], subject_id=d["subject_id"],
            name=d["name"], level=d["level"], difficulty=d["difficulty"],
            mastery=d["mastery"], status=d["status"], source=d["source"],
            summary=d["summary"], sort=d["sort"], icon=d["icon"], notes=d["notes"],
            prerequisites=d["prerequisites"], question_count=d["question_count"],
            children=[to_node_out(c) for c in d["children"]],
        )
    return to_node_out(root)
