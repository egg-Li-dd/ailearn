"""知识点关联增强 API（Phase 3）。

端点：
- POST /api/v1/knowledge/enhance/prerequisites/{chapter_id}  分析章节前置依赖
- POST /api/v1/knowledge/enhance/notes/{node_id}             生成单个知识点笔记
- POST /api/v1/knowledge/enhance/notes/batch                  批量生成笔记
- GET  /api/v1/knowledge/enhance/weak-points/{subject_id}    薄弱点诊断
- GET  /api/v1/knowledge/enhance/graph/{subject_id}           获取知识图谱数据
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..services.ai_gateway import AiGatewayError
from ..services.knowledge_enhancer import (
    analyze_prerequisites_for_chapter,
    generate_notes_for_node,
    generate_notes_batch,
    diagnose_weak_points,
    get_knowledge_graph,
)

logger = logging.getLogger("ailearn.knowledge_enhancer_api")

router = APIRouter(prefix="/api/v1", tags=["knowledge_enhancer"])


# ============================================================
# 请求模型
# ============================================================

class BatchNotesRequest(BaseModel):
    node_ids: list[int] = Field(..., description="知识点 ID 列表")
    auto_apply: bool = Field(True, description="是否自动写入 notes 字段")


# ============================================================
# 端点
# ============================================================

@router.post("/knowledge/enhance/prerequisites/{chapter_id}")
async def analyze_prerequisites(
    chapter_id: int,
    auto_apply: bool = True,
    db: Session = Depends(get_db),
):
    """分析章节下所有知识点的前置依赖关系。"""
    try:
        result = await analyze_prerequisites_for_chapter(
            db, chapter_id, auto_apply=auto_apply
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return result


@router.post("/knowledge/enhance/notes/{node_id}")
async def generate_notes(
    node_id: int,
    auto_apply: bool = True,
    db: Session = Depends(get_db),
):
    """为单个知识点生成详细笔记。"""
    try:
        notes = await generate_notes_for_node(db, node_id, auto_apply=auto_apply)
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "node_id": node_id,
        "notes": notes,
        "applied": auto_apply,
    }


@router.post("/knowledge/enhance/notes/batch")
async def generate_notes_batch_api(
    req: BatchNotesRequest,
    db: Session = Depends(get_db),
):
    """批量为知识点生成笔记。"""
    if not req.node_ids:
        raise HTTPException(status_code=400, detail="知识点 ID 列表不能为空")

    try:
        result = await generate_notes_batch(
            db, req.node_ids, auto_apply=req.auto_apply
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e

    return {
        "total": result["total"],
        "success": result["success"],
        "failed": result["failed"],
        "failures": result["failures"],
        "message": f"笔记生成完成：成功 {result['success']}/{result['total']}",
    }


@router.get("/knowledge/enhance/weak-points/{subject_id}")
async def get_weak_points(
    subject_id: int,
    db: Session = Depends(get_db),
):
    """诊断科目下的薄弱知识点。"""
    weak_points = diagnose_weak_points(db, subject_id)
    return {
        "subject_id": subject_id,
        "total": len(weak_points),
        "high": sum(1 for w in weak_points if w["level"] == "high"),
        "medium": sum(1 for w in weak_points if w["level"] == "medium"),
        "low": sum(1 for w in weak_points if w["level"] == "low"),
        "weak_points": weak_points,
    }


@router.get("/knowledge/enhance/graph/{subject_id}")
async def get_graph(
    subject_id: int,
    db: Session = Depends(get_db),
):
    """获取科目的知识图谱数据（节点+边，用于前端可视化）。"""
    graph = get_knowledge_graph(db, subject_id)
    return graph
