"""知识库路由：树 CRUD + 考纲粘贴建树 + 掌握度更新 + 拖拽 + 详情 + 导出。"""
import csv
import io
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_db
from ..models import Course, KnowledgeNode, MasteryRecord, QuizQuestion
from ..models.enums import NodeStatus, Source
from ..schemas.knowledge import (
    CopySubtreeRequest,
    ImportConfirmRequest,
    ImportOutlineRequest,
    ImportPreviewOut,
    MasteryHistoryOut,
    MasteryUpdateRequest,
    NodeBatchDelete,
    NodeCreate,
    NodeDetailOut,
    NodeMoveRequest,
    NodeOut,
    NodeSortItem,
    NodeUpdate,
    PrerequisitesUpdate,
)
from ..services.ai_gateway import AiGatewayError
from ..services.audit_service import log as audit_log
from ..services import task_center
from ..services.knowledge_refine import (
    batch_refine_course,
    get_refine_stats,
    get_refined_params,
    is_refined,
    refine_node,
    validate_params,
)
from ..services.knowledge_service import build_tree_efficient, get_single_node_tree
from ..services.mastery import apply_mastery_update

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

# 内存存储导入预览（preview_id -> items）
_import_previews: dict[str, list] = {}


def _node_to_out(db: Session, node: KnowledgeNode) -> NodeOut:
    """递归构建节点输出（含子节点）。"""
    children = list(db.scalars(
        select(KnowledgeNode)
        .where(KnowledgeNode.parent_id == node.id)
        .order_by(KnowledgeNode.sort, KnowledgeNode.id)
    ))
    question_count = 0
    if node.quiz_ids:
        try:
            question_count = len(json.loads(node.quiz_ids))
        except (json.JSONDecodeError, TypeError):
            pass
    return NodeOut(
        id=node.id, parent_id=node.parent_id, subject_id=node.subject_id,
        name=node.name, level=node.level, difficulty=node.difficulty,
        mastery=node.mastery, status=node.status, source=node.source,
        summary=node.summary, sort=node.sort, icon=node.icon, notes=node.notes,
        prerequisites=node.prerequisites, question_count=question_count,
        children=[_node_to_out(db, c) for c in children],
    )


def _get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{label} 不存在")
    return obj


def _infer_level(db: Session, parent_id: int | None, subject_id: int | None) -> int:
    if parent_id is None:
        return 1
    parent = db.get(KnowledgeNode, parent_id)
    if not parent:
        return 2
    return parent.level + 1


def _is_descendant(db: Session, ancestor_id: int, node_id: int) -> bool:
    """判断 node_id 是否是 ancestor_id 的子孙节点（防止循环引用）。"""
    if ancestor_id == node_id:
        return True
    current = db.get(KnowledgeNode, node_id)
    while current and current.parent_id:
        if current.parent_id == ancestor_id:
            return True
        current = db.get(KnowledgeNode, current.parent_id)
    return False


def _recalc_parent_mastery(db: Session, node_id: int) -> None:
    """父节点掌握度 = 子节点掌握度加权平均。"""
    node = db.get(KnowledgeNode, node_id)
    if not node or node.parent_id is None:
        return
    children = list(db.scalars(select(KnowledgeNode).where(KnowledgeNode.parent_id == node.parent_id)))
    if not children:
        return
    total_weight = sum((len(json.loads(c.quiz_ids)) if c.quiz_ids else 1) for c in children)
    weighted_sum = sum(c.mastery * (len(json.loads(c.quiz_ids)) if c.quiz_ids else 1) for c in children)
    parent = db.get(KnowledgeNode, node.parent_id)
    parent.mastery = int(weighted_sum / total_weight) if total_weight else 0
    db.commit()
    _recalc_parent_mastery(db, parent.id)


# ==================== 树查询 ====================

@router.get("/tree", response_model=list[NodeOut])
def get_tree(
    subject_id: int | None = None,
    search: str | None = None,
    mastery_min: int | None = None,
    mastery_max: int | None = None,
    has_quiz: bool | None = None,
    max_level: int | None = None,
    db: Session = Depends(get_db),
):
    """整棵知识树（N+1优化：递归CTE一次性查询+内存建树）。"""
    return build_tree_efficient(
        db, subject_id=subject_id, search=search,
        mastery_min=mastery_min, mastery_max=mastery_max,
        max_level=max_level,
    )


@router.get("/search", response_model=list[dict])
def search_nodes(keyword: str, subject_id: int | None = None, limit: int = 10, db: Session = Depends(get_db)):
    """按名称模糊搜索知识点。"""
    if not keyword.strip():
        return []
    stmt = select(KnowledgeNode).where(KnowledgeNode.name.contains(keyword.strip()))
    if subject_id is not None:
        stmt = stmt.where(KnowledgeNode.subject_id == subject_id)
    rows = list(db.scalars(stmt.order_by(KnowledgeNode.id).limit(limit)))
    return [{"id": n.id, "name": n.name, "mastery": n.mastery, "level": n.level,
             "subject_id": n.subject_id, "parent_id": n.parent_id} for n in rows]


# ==================== 节点 CRUD ====================

@router.get("/nodes/{node_id}", response_model=NodeOut)
def get_node(node_id: int, db: Session = Depends(get_db)):
    result = get_single_node_tree(db, node_id)
    if not result:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return result


@router.post("/nodes", response_model=NodeOut, status_code=201)
def create_node(payload: NodeCreate, db: Session = Depends(get_db)):
    if payload.parent_id is not None:
        _get_or_404(db, KnowledgeNode, payload.parent_id, "父节点")
    if payload.subject_id is not None:
        _get_or_404(db, Course, payload.subject_id, "科目")
    if payload.parent_id is None and payload.subject_id is None:
        raise HTTPException(status_code=422, detail="根节点必须指定科目")
    node = KnowledgeNode(
        parent_id=payload.parent_id,
        subject_id=payload.subject_id if payload.parent_id is None else None,
        name=payload.name, level=_infer_level(db, payload.parent_id, payload.subject_id),
        difficulty=payload.difficulty, summary=payload.summary,
        sort=payload.sort, icon=payload.icon, notes=payload.notes,
        prerequisites=payload.prerequisites,
        source=Source.MANUAL, status=NodeStatus.UNTOUCHED,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    audit_log(db, "knowledge", "create", node.id, node.name, {"parent_id": node.parent_id})
    return get_single_node_tree(db, node.id)


@router.put("/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: int, payload: NodeUpdate, db: Session = Depends(get_db)):
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    old_name = node.name
    data = payload.model_dump(exclude_unset=True)
    if data.get("parent_id") is not None:
        _get_or_404(db, KnowledgeNode, data["parent_id"], "父节点")
        if data["parent_id"] == node.id:
            raise HTTPException(status_code=422, detail="不能将节点挂到自己下")
        if _is_descendant(db, node.id, data["parent_id"]):
            raise HTTPException(status_code=422, detail="不能将节点移动到自己的子孙节点下")
        data["level"] = _infer_level(db, data["parent_id"], None)
    if "mastery" in data:
        node.mastery = max(0, min(100, int(data["mastery"])))
        del data["mastery"]
        _recalc_parent_mastery(db, node.id)
    for k, v in data.items():
        setattr(node, k, v)
    db.commit()
    db.refresh(node)
    audit_log(db, "knowledge", "update", node.id, node.name, {"old_name": old_name, "changed": list(data.keys())})
    return get_single_node_tree(db, node.id)


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: int, cascade: bool = False, db: Session = Depends(get_db)):
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    deleted_names = [node.name]
    if cascade:
        def get_descendants(nid: int) -> list[int]:
            children = list(db.scalars(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == nid)))
            result = list(children)
            for cid in children:
                result.extend(get_descendants(cid))
            return result
        descendants = get_descendants(node_id)
        for did in descendants + [node_id]:
            n = db.get(KnowledgeNode, did)
            if n:
                deleted_names.append(n.name)
                db.delete(n)
    else:
        has_children = db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == node_id).limit(1))
        if has_children:
            raise HTTPException(status_code=409, detail="存在子节点，请先删除子节点或使用 cascade=true")
        db.delete(node)
    db.commit()
    audit_log(db, "knowledge", "delete", node_id, node.name, {"cascade": cascade, "deleted_count": len(deleted_names)})


@router.delete("/nodes/batch")
def batch_delete_nodes(payload: NodeBatchDelete, cascade: bool = False, db: Session = Depends(get_db)):
    deleted = 0
    for nid in payload.ids:
        node = db.get(KnowledgeNode, nid)
        if not node:
            continue
        if cascade:
            def get_descendants(nid: int) -> list[int]:
                children = list(db.scalars(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == nid)))
                result = list(children)
                for cid in children:
                    result.extend(get_descendants(cid))
                return result
            for did in get_descendants(nid) + [nid]:
                n = db.get(KnowledgeNode, did)
                if n:
                    db.delete(n)
                    deleted += 1
        else:
            has_children = db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == nid).limit(1))
            if not has_children:
                db.delete(node)
                deleted += 1
    db.commit()
    audit_log(db, "knowledge", "batch_delete", None, "批量删除", {"ids": payload.ids, "deleted": deleted, "cascade": cascade})
    return {"deleted": deleted}


# ==================== 拖拽移动 ====================

@router.put("/nodes/{node_id}/move", response_model=NodeOut)
def move_node(node_id: int, payload: NodeMoveRequest, db: Session = Depends(get_db)):
    """拖拽移动节点，校验循环引用。"""
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    old_parent = node.parent_id
    if payload.parent_id is not None:
        _get_or_404(db, KnowledgeNode, payload.parent_id, "父节点")
        if payload.parent_id == node.id:
            raise HTTPException(status_code=422, detail="不能将节点挂到自己下")
        if _is_descendant(db, node.id, payload.parent_id):
            raise HTTPException(status_code=422, detail="不能将节点移动到自己的子孙节点下")
    node.parent_id = payload.parent_id
    node.subject_id = None if payload.parent_id is not None else node.subject_id
    node.sort = payload.sort
    node.level = _infer_level(db, payload.parent_id, None)
    db.commit()
    db.refresh(node)
    audit_log(db, "knowledge", "move", node.id, node.name, {"old_parent": old_parent, "new_parent": node.parent_id})
    return get_single_node_tree(db, node.id)


@router.put("/nodes/sort")
def sort_nodes(payload: list[NodeSortItem], db: Session = Depends(get_db)):
    """批量更新同级排序。"""
    for item in payload:
        node = db.get(KnowledgeNode, item.id)
        if node:
            node.sort = item.sort
    db.commit()
    if payload:
        audit_log(db, "knowledge", "sort", None, "批量排序", {"count": len(payload)})
    return {"updated": len(payload)}


# ==================== 节点详情 ====================

@router.get("/nodes/{node_id}/detail", response_model=NodeDetailOut)
def get_node_detail(node_id: int, db: Session = Depends(get_db)):
    """节点完整详情（含题目/掌握度历史/前置后续关联）。"""
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")

    # 题目列表
    questions = []
    if node.quiz_ids:
        try:
            qids = json.loads(node.quiz_ids)
            for qid in qids:
                q = db.get(QuizQuestion, qid)
                if q:
                    questions.append({"id": q.id, "title": q.question[:100] if hasattr(q, 'question') else str(q.id),
                                      "difficulty": getattr(q, 'difficulty', 1)})
        except (json.JSONDecodeError, TypeError):
            pass

    # 掌握度历史
    history = list(db.scalars(
        select(MasteryRecord).where(MasteryRecord.node_id == node_id).order_by(MasteryRecord.created_at.desc()).limit(20)
    ))
    mastery_history = [{"date": r.created_at.isoformat(), "value": r.new_value,
                         "reason": r.reason, "source": r.source} for r in reversed(history)]

    # 前置知识点
    prerequisites = []
    if node.prerequisites:
        try:
            pids = json.loads(node.prerequisites)
            for pid in pids:
                p = db.get(KnowledgeNode, pid)
                if p:
                    prerequisites.append({"id": p.id, "name": p.name, "mastery": p.mastery})
        except (json.JSONDecodeError, TypeError):
            pass

    # 后续知识点（哪些节点把当前节点设为前置）
    successors = []
    all_nodes = list(db.scalars(select(KnowledgeNode).where(KnowledgeNode.prerequisites.isnot(None))))
    for n in all_nodes:
        try:
            pids = json.loads(n.prerequisites)
            if node_id in pids:
                successors.append({"id": n.id, "name": n.name, "mastery": n.mastery})
        except (json.JSONDecodeError, TypeError):
            pass

    return NodeDetailOut(
        id=node.id, parent_id=node.parent_id, subject_id=node.subject_id,
        name=node.name, level=node.level, difficulty=node.difficulty,
        mastery=node.mastery, status=node.status, icon=node.icon,
        summary=node.summary, notes=node.notes, sort=node.sort,
        question_count=len(questions), prerequisites=prerequisites,
        successors=successors, mastery_history=mastery_history, questions=questions,
    )


@router.get("/nodes/{node_id}/mastery-history", response_model=MasteryHistoryOut)
def get_mastery_history(node_id: int, limit: int = 20, db: Session = Depends(get_db)):
    """掌握度变化历史。"""
    _get_or_404(db, KnowledgeNode, node_id, "知识点")
    records = list(db.scalars(
        select(MasteryRecord).where(MasteryRecord.node_id == node_id).order_by(MasteryRecord.created_at.desc()).limit(limit)
    ))
    return MasteryHistoryOut(
        node_id=node_id,
        records=[{"date": r.created_at.isoformat(), "old_value": r.old_value,
                  "new_value": r.new_value, "reason": r.reason, "source": r.source}
                 for r in reversed(records)],
    )


@router.put("/nodes/{node_id}/prerequisites")
def update_prerequisites(node_id: int, payload: PrerequisitesUpdate, db: Session = Depends(get_db)):
    """更新前置知识点关联。"""
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    # 校验所有前置节点存在
    for pid in payload.ids:
        _get_or_404(db, KnowledgeNode, pid, "前置知识点")
    node.prerequisites = json.dumps(payload.ids)
    db.commit()
    return {"updated": len(payload.ids)}


# ==================== AI 大纲导入（两步：预览 + 确认）====================

@router.post("/import-preview", response_model=ImportPreviewOut)
async def import_outline_preview(payload: ImportOutlineRequest):
    """AI 大纲导入预览（不写入 DB）。"""
    _get_or_404(SessionLocal(), Course, payload.subject_id, "科目")
    try:
        from ..services.ai_gateway import chat_once
        set_function_type("knowledge")
        reply = await chat_once(
            [
                {"role": "system", "content": (
                    "你是知识工程助手。请把用户粘贴的课程大纲/目录解析为 JSON 树结构。"
                    "输出格式（严格 JSON，不要任何其他文字）："
                    '{"items":[{"name":"章名","children":[{"name":"节名","children":[]}]}]}'
                    "节点名保持原文（去编号），每层最多 30 项。"
                )},
                {"role": "user", "content": payload.text[:8000]},
            ],
            temperature=0.2,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=400, detail=f"AI 建树失败：{e}") from e

    try:
        tree = json.loads(reply.strip())
        items = tree.get("items", [])
    except (json.JSONDecodeError, AttributeError):
        raise HTTPException(status_code=422, detail="AI 返回无法解析")

    def count_nodes(nodes: list) -> int:
        return sum(1 + count_nodes(n.get("children", [])) for n in nodes)

    preview_id = str(uuid.uuid4())[:8]
    _import_previews[preview_id] = items
    return ImportPreviewOut(preview_id=preview_id, items=items, total_nodes=count_nodes(items))


@router.post("/import-confirm", response_model=list[NodeOut])
def import_outline_confirm(payload: ImportConfirmRequest, db: Session = Depends(get_db)):
    """确认导入预览结果。"""
    items = _import_previews.pop(payload.preview_id, None)
    if items is None:
        raise HTTPException(status_code=404, detail="预览已过期，请重新生成")
    _get_or_404(db, Course, payload.subject_id, "科目")

    def build(parent_id: int | None, nodes: list, level: int) -> None:
        for it in nodes:
            name = str(it.get("name", "")).strip()
            if not name:
                continue
            node = KnowledgeNode(
                parent_id=parent_id,
                subject_id=payload.subject_id if parent_id is None else None,
                name=name[:128], level=level,
                source=Source.PASTE_OUTLINE, status=NodeStatus.UNTOUCHED,
            )
            db.add(node)
            db.flush()
            build(node.id, it.get("children") or [], level + 1)

    build(None, items, 1)
    db.commit()
    audit_log(db, "knowledge", "ai_import", None, "AI大纲导入", {"subject_id": payload.subject_id, "root_count": len(items)})
    return build_tree_efficient(db, subject_id=payload.subject_id)


# 兼容旧 API：直接导入（一步）
@router.post("/import-outline", response_model=list[NodeOut])
async def import_outline(payload: ImportOutlineRequest, db: Session = Depends(get_db)):
    """兼容旧 API：粘贴考纲/目录文本 → AI 解析为章节骨架（直接写入）。"""
    _get_or_404(db, Course, payload.subject_id, "科目")
    try:
        from ..services.ai_gateway import chat_once
        set_function_type("knowledge")
        reply = await chat_once(
            [
                {"role": "system", "content": (
                    "你是知识工程助手。请把用户粘贴的课程大纲/目录解析为 JSON 树结构。"
                    "输出格式（严格 JSON，不要任何其他文字）："
                    '{"items":[{"name":"章名","children":[{"name":"节名","children":[]}]}]}'
                    "只保留 3 层以内的结构，节点名保持原文（去编号），每层最多 30 项。"
                )},
                {"role": "user", "content": payload.text[:8000]},
            ],
            temperature=0.2,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=400, detail=f"AI 建树失败：{e}") from e

    try:
        tree = json.loads(reply.strip())
        items = tree.get("items", [])
    except (json.JSONDecodeError, AttributeError):
        raise HTTPException(status_code=422, detail="AI 返回无法解析")

    def build(parent_id: int | None, nodes: list, level: int) -> None:
        for it in nodes:
            name = str(it.get("name", "")).strip()
            if not name:
                continue
            node = KnowledgeNode(
                parent_id=parent_id,
                subject_id=payload.subject_id if parent_id is None else None,
                name=name[:128], level=level,
                source=Source.PASTE_OUTLINE, status=NodeStatus.UNTOUCHED,
            )
            db.add(node)
            db.flush()
            build(node.id, it.get("children") or [], level + 1)

    build(None, items, 1)
    db.commit()
    audit_log(db, "knowledge", "ai_import", None, "AI大纲导入(兼容)", {"subject_id": payload.subject_id, "root_count": len(items)})
    return build_tree_efficient(db, subject_id=payload.subject_id)


# ==================== 导出 ====================

@router.get("/export")
def export_tree(subject_id: int | None = None, format: str = "json", db: Session = Depends(get_db)):
    """导出知识树（json/md/opml）。"""
    tree = [n.model_dump() for n in build_tree_efficient(db, subject_id=subject_id)]
    audit_log(db, "knowledge", "export", None, "导出知识树", {"subject_id": subject_id, "format": format})

    if format == "json":
        return {"format": "json", "tree": tree}

    elif format == "md":
        def to_md(nodes: list, depth: int = 0) -> str:
            lines = []
            for n in nodes:
                prefix = "#" * min(depth + 1, 6)
                lines.append(f"{prefix} {n['name']}")
                if n.get("summary"):
                    lines.append(f"\n{n['summary']}\n")
                if n["children"]:
                    lines.append(to_md(n["children"], depth + 1))
            return "\n".join(lines)
        return {"format": "md", "content": to_md(tree)}

    elif format == "opml":
        def to_opml(nodes: list) -> str:
            items = []
            for n in nodes:
                children = to_opml(n["children"]) if n["children"] else ""
                items.append(f'<outline text="{n["name"]}" _note="{n.get("summary","")}">{children}</outline>')
            return "".join(items)
        opml = f'<?xml version="1.0" encoding="UTF-8"?><opml version="2.0"><body>{to_opml(tree)}</body></opml>'
        return {"format": "opml", "content": opml}

    else:
        raise HTTPException(status_code=400, detail="不支持的格式，可选 json/md/opml")


# ==================== 复制子树 ====================

@router.post("/nodes/{node_id}/copy-subtree", response_model=NodeOut)
def copy_subtree(node_id: int, payload: CopySubtreeRequest, db: Session = Depends(get_db)):
    """复制子树到目标科目。"""
    source = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    _get_or_404(db, Course, payload.target_subject_id, "目标科目")

    def copy_node(src: KnowledgeNode, new_parent_id: int | None, is_root: bool) -> KnowledgeNode:
        node = KnowledgeNode(
            parent_id=new_parent_id,
            subject_id=payload.target_subject_id if is_root else None,
            name=src.name + " (副本)", level=src.level if is_root else _infer_level(db, new_parent_id, None),
            difficulty=src.difficulty, summary=src.summary, icon=src.icon, notes=src.notes,
            sort=src.sort, source=Source.MANUAL, status=NodeStatus.UNTOUCHED,
        )
        db.add(node)
        db.flush()
        children = list(db.scalars(select(KnowledgeNode).where(KnowledgeNode.parent_id == src.id)))
        for child in children:
            copy_node(child, node.id, False)
        return node

    new_root = copy_node(source, None, True)
    db.commit()
    db.refresh(new_root)
    audit_log(db, "knowledge", "copy_subtree", new_root.id, new_root.name, {"source_id": node_id, "target_subject": payload.target_subject_id})
    return get_single_node_tree(db, new_root.id)


# ==================== 掌握度更新 ====================

@router.post("/nodes/{node_id}/mastery", response_model=NodeOut)
def update_mastery(node_id: int, payload: MasteryUpdateRequest, db: Session = Depends(get_db)):
    """手动/外部掌握度更新（自评、做题结果等）。"""
    _get_or_404(db, KnowledgeNode, node_id, "知识点")
    apply_mastery_update(
        db, node_id, new_mastery=int(payload.value),
        reason=payload.reason, source=payload.source,
    )
    node = db.get(KnowledgeNode, node_id)
    _recalc_parent_mastery(db, node_id)
    audit_log(db, "knowledge", "update_mastery", node_id, node.name, {"new_value": payload.value, "reason": payload.reason})
    return get_single_node_tree(db, node_id)


# ==================== 知识点细化（参数表）====================

async def _execute_refine_node(node_id: int, force: bool):
    """后台执行知识点细化。"""
    import asyncio
    from contextvars import ContextVar
    db = SessionLocal()
    try:
        node = db.get(KnowledgeNode, node_id)
        if not node:
            task_center.fail_task(error="知识点不存在")
            return
        task_center.update_progress(stage="正在调用 AI 细化知识点...", progress=20)
        try:
            params = await refine_node(db, node_id, force=force)
        except AiGatewayError as e:
            task_center.fail_task(error=f"AI 细化失败：{e}")
            return
        except ValueError as e:
            task_center.fail_task(error=str(e))
            return
        task_center.update_progress(stage="正在验证参数表...", progress=80)
        audit_log(db, "knowledge", "refine", node_id, node.name, {"force": force})
        task_center.update_progress(progress=100)
        task_center.complete_task(result={
            "node_id": node_id,
            "node_name": node.name,
            "refined": True,
            "validation_errors": validate_params(params),
            "redirect": f"/knowledge?node={node_id}",
        })
    except Exception as e:
        task_center.fail_task(error=str(e))
    finally:
        db.close()


@router.post("/nodes/{node_id}/refine")
async def refine_node_params(node_id: int, force: bool = False, db: Session = Depends(get_db)):
    """AI 细化知识点（后台任务）。立即返回 task_id，通过任务悬浮窗查看进度。"""
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    task_id = task_center.create_task(
        task_type="knowledge_refine",
        title=f"知识点细化：{node.name}",
        metadata={"node_id": node_id, "force": force},
    )
    token = task_center._current_task_id.set(task_id)
    try:
        task_center.mark_running(task_id)
        asyncio.create_task(_execute_refine_node(node_id, force))
    finally:
        task_center._current_task_id.reset(token)
    return {"task_id": task_id, "status": "pending", "message": "知识点细化任务已创建"}


@router.get("/nodes/{node_id}/params")
def get_node_params(node_id: int, db: Session = Depends(get_db)):
    """获取知识点的结构化参数表（从 notes 字段解析）。"""
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")
    params = get_refined_params(node)
    return {
        "node_id": node_id,
        "refined": params is not None,
        "is_valid": is_refined(node),
        "params": params,
        "summary": node.summary,
    }


@router.put("/nodes/{node_id}/params")
def update_node_params(node_id: int, payload: dict, db: Session = Depends(get_db)):
    """手动更新知识点参数表（教师可调整 AI 生成的参数）。

    请求体为参数表 dict（definition/core_elements/key_terms/formulas/common_mistakes/scope_boundary/prerequisites_desc）。
    会自动包装为 schema_version 格式写入 notes，definition 同步写入 summary。
    """
    node = _get_or_404(db, KnowledgeNode, node_id, "知识点")

    # 校验必填字段
    errors = validate_params(payload)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "参数表校验失败", "errors": errors})

    # 包装为完整格式写入 notes
    from ..services.knowledge_refine import PARAMS_SCHEMA_VERSION, _now_iso
    full_data = {
        "schema_version": PARAMS_SCHEMA_VERSION,
        "refined_at": _now_iso(),
        "params": payload,
    }
    node.notes = json.dumps(full_data, ensure_ascii=False)
    node.summary = payload.get("definition", node.summary or "")
    db.commit()
    db.refresh(node)
    audit_log(db, "knowledge", "update_params", node_id, node.name, {"fields": list(payload.keys())})
    return {"node_id": node_id, "updated": True, "params": payload}


# ==================== 知识点参数表 CSV 批量导入导出 ====================

_PARAMS_CSV_COLUMNS = [
    "node_id", "name", "level",
    "definition", "core_elements", "key_terms",
    "formulas", "common_mistakes", "scope_boundary", "prerequisites_desc",
]
_ARRAY_SEP = " | "


def _params_to_csv_row(node: KnowledgeNode) -> dict:
    """将节点参数表转为 CSV 行。"""
    params = get_refined_params(node) or {}
    def _arr(v): return _ARRAY_SEP.join(v) if isinstance(v, list) else (v or "")
    return {
        "node_id": node.id,
        "name": node.name,
        "level": node.level,
        "definition": params.get("definition", ""),
        "core_elements": _arr(params.get("core_elements", [])),
        "key_terms": _arr(params.get("key_terms", [])),
        "formulas": _arr(params.get("formulas", [])),
        "common_mistakes": _arr(params.get("common_mistakes", [])),
        "scope_boundary": params.get("scope_boundary", ""),
        "prerequisites_desc": params.get("prerequisites_desc", ""),
    }


def _csv_row_to_params(row: dict) -> dict:
    """将 CSV 行解析为参数表 dict。"""
    def _arr(v):
        if not v:
            return []
        return [s.strip() for s in str(v).split(_ARRAY_SEP) if s.strip()]
    params = {
        "definition": (row.get("definition") or "").strip(),
        "core_elements": _arr(row.get("core_elements")),
        "key_terms": _arr(row.get("key_terms")),
        "formulas": _arr(row.get("formulas")),
        "common_mistakes": _arr(row.get("common_mistakes")),
        "scope_boundary": (row.get("scope_boundary") or "").strip(),
    }
    prereq = (row.get("prerequisites_desc") or "").strip()
    if prereq:
        params["prerequisites_desc"] = prereq
    return params


@router.get("/params/export")
def export_params_csv(
    subject_id: int | None = None,
    only_refined: bool = False,
    db: Session = Depends(get_db),
):
    """批量导出知识点参数表为 CSV。

    Args:
        subject_id: 限定科目，不传则导出全部
        only_refined: True 时只导出已有参数表的节点
    """
    stmt = select(KnowledgeNode)
    if subject_id is not None:
        # 科目下的所有节点：根节点 subject_id 匹配，子节点通过 parent 递归
        root_ids = [n.id for n in db.scalars(
            select(KnowledgeNode.id).where(
                KnowledgeNode.parent_id.is_(None),
                KnowledgeNode.subject_id == subject_id,
            )
        )]
        if not root_ids:
            stmt = stmt.where(KnowledgeNode.id == -1)  # 空结果
        else:
            # 递归收集所有子孙
            all_ids = set(root_ids)
            frontier = list(root_ids)
            while frontier:
                children = list(db.scalars(
                    select(KnowledgeNode.id).where(KnowledgeNode.parent_id.in_(frontier))
                ))
                new_ids = [c for c in children if c not in all_ids]
                all_ids.update(new_ids)
                frontier = new_ids
            stmt = stmt.where(KnowledgeNode.id.in_(all_ids))

    nodes = list(db.scalars(stmt.order_by(KnowledgeNode.level, KnowledgeNode.sort, KnowledgeNode.id)))

    if only_refined:
        nodes = [n for n in nodes if is_refined(n)]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_PARAMS_CSV_COLUMNS)
    writer.writeheader()
    for node in nodes:
        writer.writerow(_params_to_csv_row(node))

    from fastapi.responses import PlainTextResponse
    audit_log(db, "knowledge", "export_params", None, "导出参数表CSV", {
        "subject_id": subject_id, "count": len(nodes), "only_refined": only_refined,
    })
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="knowledge_params_{subject_id or "all"}.csv"'},
    )


@router.post("/params/import")
async def import_params_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """批量导入知识点参数表 CSV。

    CSV 必须包含 node_id 列（用于匹配节点），其他列为参数字段。
    数组字段用 " | " 分隔。
    只更新校验通过的节点，返回成功/失败统计。
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    content = await file.read()
    # 处理 BOM
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if "node_id" not in (reader.fieldnames or []):
        raise HTTPException(status_code=400, detail="CSV 必须包含 node_id 列")

    updated = 0
    skipped = 0
    errors: list[dict] = []

    for row in reader:
        try:
            node_id = int(str(row.get("node_id", "")).strip())
        except (ValueError, TypeError):
            skipped += 1
            errors.append({"row": row, "error": "node_id 不是有效整数"})
            continue

        node = db.get(KnowledgeNode, node_id)
        if not node:
            skipped += 1
            errors.append({"node_id": node_id, "error": "节点不存在"})
            continue

        params = _csv_row_to_params(row)
        # 跳过完全空的行（没有任何参数）
        if not params["definition"] and not params["core_elements"] and not params["scope_boundary"]:
            skipped += 1
            continue

        validation_errors = validate_params(params)
        if validation_errors:
            skipped += 1
            errors.append({"node_id": node_id, "name": node.name, "errors": validation_errors})
            continue

        # 写入
        from ..services.knowledge_refine import PARAMS_SCHEMA_VERSION, _now_iso
        full_data = {
            "schema_version": PARAMS_SCHEMA_VERSION,
            "refined_at": _now_iso(),
            "params": params,
        }
        node.notes = json.dumps(full_data, ensure_ascii=False)
        node.summary = params.get("definition", node.summary or "")
        updated += 1

    db.commit()
    audit_log(db, "knowledge", "import_params", None, "导入参数表CSV", {
        "updated": updated, "skipped": skipped, "filename": file.filename,
    })
    return {
        "updated": updated,
        "skipped": skipped,
        "total": updated + skipped,
        "errors": errors[:20],  # 最多返回前20条错误
    }


# ============================================================
# 批量预细化
# ============================================================

@router.get("/refine/stats")
def refine_stats(course_id: int | None = Query(None), db: Session = Depends(get_db)):
    """统计知识点细化情况（valid/invalid/unrefined）。"""
    return get_refine_stats(db, course_id)


@router.post("/refine/batch")
async def refine_batch(
    course_id: int = Query(..., description="课程ID"),
    force: bool = Query(False, description="是否强制重新细化所有知识点（包括valid的）"),
    only_invalid: bool = Query(True, description="是否只细化invalid参数表的知识点"),
    delay: float = Query(1.0, description="每个请求之间的延迟（秒），避免API限流"),
    limit: int = Query(50, description="本次最多处理的知识点数量（0=不限制）"),
    db: Session = Depends(get_db),
):
    """批量细化某个课程的知识点。

    由于调用AI可能需要较长时间，建议通过 limit 参数分批处理。
    默认只细化 invalid 参数表的知识点，valid 的会跳过。
    """
    from ..models import KnowledgeNode
    from sqlalchemy import select as sa_select
    import asyncio

    # 筛选需要细化的节点
    stmt = sa_select(KnowledgeNode).where(
        KnowledgeNode.subject_id == course_id,
        KnowledgeNode.level >= 3,
    ).order_by(KnowledgeNode.id)

    nodes = list(db.scalars(stmt))
    to_refine = []

    for node in nodes:
        if force:
            to_refine.append(node)
            continue
        if only_invalid:
            if node.notes:
                try:
                    data = json.loads(node.notes)
                    if data.get("params_status") == "invalid":
                        to_refine.append(node)
                except (json.JSONDecodeError, TypeError):
                    pass
        elif not is_refined(node):
            to_refine.append(node)

    if limit > 0:
        to_refine = to_refine[:limit]

    total = len(to_refine)
    success = 0
    failed = 0
    errors = []

    for i, node in enumerate(to_refine):
        try:
            await refine_node(db, node.id, force=True)
            success += 1
        except Exception as e:
            failed += 1
            errors.append({"id": node.id, "name": node.name, "error": str(e)[:100]})

        if delay > 0 and i < total - 1:
            await asyncio.sleep(delay)

    return {
        "course_id": course_id,
        "total": total,
        "success": success,
        "failed": failed,
        "errors": errors[:20],
    }


# ============================================================
# 长按菜单：知识点修改整合 + 错误修正
# ============================================================


class IntegrateRequest(BaseModel):
    original_content: str = Field(description="原始内容")
    modified_content: str = Field(description="修改后的内容")
    source: str = Field(default="long_press_edit", description="来源")


class CorrectRequest(BaseModel):
    original_content: str = Field(description="原始内容")
    error_description: str = Field(description="错误描述")
    source: str = Field(default="long_press_error", description="来源")


@router.post("/integrate")
async def integrate_knowledge(payload: IntegrateRequest, db: Session = Depends(get_db)):
    """修改知识点并整合到知识库（长按菜单）。

    AI分析修改后的内容，提取知识点并更新/创建知识库节点。
    """
    from ..ai.gateway import chat_stream, AiGatewayError

    system_prompt = f"""你是一个知识库整合专家。用户修改了一段内容，请分析修改后的内容，提取其中的知识点，并给出整合建议。

原始内容：
{payload.original_content}

修改后的内容：
{payload.modified_content}

请分析：
1. 修改了哪些知识点？
2. 新增了哪些知识点？
3. 删除了哪些知识点？
4. 每个知识点的准确定义、核心要点、典型例子、常见误区

输出JSON格式（只输出JSON）：
{{
    "modified_nodes": [
        {{"name": "知识点名", "definition": "定义", "key_points": ["要点1", "要点2"], "examples": ["例子1"], "pitfalls": ["误区1"]}}
    ],
    "new_nodes": [...],
    "removed_nodes": ["知识点名1"],
    "summary": "整合总结"
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请分析并整合"},
    ]

    parts: list[str] = []
    try:
        set_function_type("knowledge")
        async for text in chat_stream(messages):
            parts.append(text)
    except AiGatewayError as e:
        raise HTTPException(status_code=500, detail=f"AI分析失败: {e}")

    raw = "".join(parts).strip()
    # 提取JSON
    import re
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        raise HTTPException(status_code=500, detail="AI返回格式错误")

    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="JSON解析失败")

    # 记录审计日志
    audit_log(db, "knowledge", "integrate", None, "长按菜单-知识点修改整合", {
        "source": payload.source,
        "modified_count": len(result.get("modified_nodes", [])),
        "new_count": len(result.get("new_nodes", [])),
    })

    return {"success": True, "result": result}


@router.post("/correct")
async def correct_knowledge(payload: CorrectRequest, db: Session = Depends(get_db)):
    """指出错误并修改入库（长按菜单）。

    AI分析错误描述，修正知识点并更新知识库。
    """
    from ..ai.gateway import chat_stream, AiGatewayError

    system_prompt = f"""你是一个知识库纠错专家。用户指出了一段内容中的错误，请分析错误并给出修正后的知识点。

原始内容：
{payload.original_content}

错误描述：
{payload.error_description}

请分析：
1. 错误在哪里？
2. 正确的内容应该是什么？
3. 修正后的知识点定义、核心要点、典型例子、常见误区

输出JSON格式（只输出JSON）：
{{
    "error_analysis": "错误分析",
    "corrected_nodes": [
        {{"name": "知识点名", "definition": "修正后的定义", "key_points": ["要点1"], "examples": ["例子1"], "pitfalls": ["误区1"]}}
    ],
    "correction_summary": "修正总结"
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请分析并修正"},
    ]

    parts: list[str] = []
    try:
        set_function_type("knowledge")
        async for text in chat_stream(messages):
            parts.append(text)
    except AiGatewayError as e:
        raise HTTPException(status_code=500, detail=f"AI分析失败: {e}")

    raw = "".join(parts).strip()
    import re
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        raise HTTPException(status_code=500, detail="AI返回格式错误")

    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="JSON解析失败")

    audit_log(db, "knowledge", "correct", None, "长按菜单-错误修正", {
        "source": payload.source,
        "corrected_count": len(result.get("corrected_nodes", [])),
    })

    return {"success": True, "result": result}
