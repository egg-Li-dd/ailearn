"""智能出题 API（Phase 2）。

端点：
- POST /api/v1/quiz/generate/batch   批量生成题目草稿
- POST /api/v1/quiz/generate/save    保存审核通过的题目
- POST /api/v1/quiz/generate/verify  单独验证一道题
- GET  /api/v1/quiz/generate/nodes   获取可选知识点列表
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Course, KnowledgeNode
from ..services.ai_gateway import AiGatewayError
from ..services.quiz_generator import (
    generate_batch,
    verify_question,
    save_questions,
    VALID_STYLES,
    STYLE_KAOYAN,
)

logger = logging.getLogger("ailearn.quiz_generator_api")

router = APIRouter(prefix="/api/v1", tags=["quiz_generator"])


# ============================================================
# 请求模型
# ============================================================

class GenerateBatchRequest(BaseModel):
    node_ids: list[int] | None = Field(None, description="指定知识点ID列表")
    chapter_id: int | None = Field(None, description="章节节点ID（取该章节下所有知识点）")
    subject_id: int | None = Field(None, description="科目ID（取该科目下所有知识点）")
    count: int = Field(10, ge=1, le=50, description="生成题目数量（1-50）")
    qtype: str | None = Field(None, description="强制题型，不填则随机")
    difficulty: int | None = Field(None, ge=1, le=5, description="强制难度1-5，不填则随机")
    style: str = Field(STYLE_KAOYAN, description="出题风格：kaoyan/textbook/basic")
    verify: bool = Field(True, description="是否执行AI答案验证")


class SaveQuestionsRequest(BaseModel):
    questions: list[dict] = Field(..., description="题目草稿列表（从生成接口返回的questions字段）")
    only_valid: bool = Field(True, description="是否只保存验证通过的题目")
    min_score: int = Field(0, ge=0, le=10, description="最低质量评分0-10")


class VerifyQuestionRequest(BaseModel):
    question: dict = Field(..., description="题目草稿数据")


# ============================================================
# 端点
# ============================================================

@router.post("/quiz/generate/batch")
async def generate_batch_api(
    req: GenerateBatchRequest,
    db: Session = Depends(get_db),
):
    """批量生成题目草稿（不入库，返回给前端审核）。"""
    # 校验参数
    if not req.node_ids and not req.chapter_id and not req.subject_id:
        raise HTTPException(status_code=400, detail="必须指定 node_ids、chapter_id 或 subject_id 其中之一")

    if req.style not in VALID_STYLES:
        raise HTTPException(status_code=400, detail=f"无效的出题风格: {req.style}，可选: {', '.join(VALID_STYLES)}")

    try:
        result = await generate_batch(
            db,
            node_ids=req.node_ids,
            chapter_id=req.chapter_id,
            subject_id=req.subject_id,
            count=req.count,
            qtype=req.qtype,
            difficulty=req.difficulty,
            style=req.style,
            verify=req.verify,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "total": result["total"],
        "success": result["success"],
        "failed": result["failed"],
        "questions": result["questions"],
        "failures": result["failures"],
        "message": f"生成完成：成功 {result['success']}/{result['total']}",
    }


@router.post("/quiz/generate/save")
async def save_questions_api(
    req: SaveQuestionsRequest,
    db: Session = Depends(get_db),
):
    """批量保存审核通过的题目到数据库。"""
    if not req.questions:
        raise HTTPException(status_code=400, detail="题目列表不能为空")

    try:
        result = save_questions(
            db,
            req.questions,
            only_valid=req.only_valid,
            min_score=req.min_score,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"保存失败: {e}") from e

    return {
        "saved": result["saved"],
        "skipped": result["skipped"],
        "question_ids": result["question_ids"],
        "message": f"保存成功：{result['saved']} 道题",
    }


@router.post("/quiz/generate/verify")
async def verify_question_api(
    req: VerifyQuestionRequest,
    db: Session = Depends(get_db),
):
    """单独验证一道题的答案正确性。"""
    try:
        result = await verify_question(req.question, db=db)
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e

    return result


@router.get("/quiz/generate/nodes")
async def get_available_nodes(
    subject_id: int | None = Query(None, description="按科目筛选"),
    db: Session = Depends(get_db),
):
    """获取可选的知识点列表（用于前端选择出题范围）。"""
    query = select(KnowledgeNode).where(KnowledgeNode.level == 4)
    if subject_id:
        query = query.where(KnowledgeNode.subject_id == subject_id)

    nodes = db.execute(query.order_by(KnowledgeNode.subject_id, KnowledgeNode.id)).scalars().all()

    # 按科目分组
    subjects = {}
    for node in nodes:
        sid = node.subject_id
        if sid not in subjects:
            course = db.get(Course, sid)
            subjects[sid] = {
                "subject_id": sid,
                "subject_name": course.name if course else f"科目{sid}",
                "nodes": [],
            }
        subjects[sid]["nodes"].append({
            "id": node.id,
            "name": node.name,
            "difficulty": node.difficulty,
            "mastery": node.mastery,
        })

    return {
        "subjects": list(subjects.values()),
        "total_nodes": len(nodes),
    }
