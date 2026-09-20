"""题目导入 API（Phase 1）。

端点：
- POST /api/v1/quiz/import/text      单题文本导入
- POST /api/v1/quiz/import/batch     批量文本导入（自动分割题号）
- POST /api/v1/quiz/import/parse     仅解析不保存（预览）
- GET  /api/v1/quiz/import/preview   预览解析结果
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..services.ai_gateway import AiGatewayError
from ..services.quiz_import import (
    import_single,
    import_batch,
    parse_question,
    generate_analysis,
    split_questions,
    find_matching_node,
)

logger = logging.getLogger("ailearn.quiz_import_api")

router = APIRouter(prefix="/api/v1", tags=["quiz_import"])


# ============================================================
# 请求/响应模型
# ============================================================

class ImportTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000, description="原始题目文本")
    node_id: int | None = Field(None, description="手动指定关联的知识点节点ID，不填则自动匹配")
    generate_analysis: bool = Field(True, description="是否生成AI解析")


class ImportBatchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="包含多道题的原始文本，按题号自动分割")
    node_id: int | None = Field(None, description="手动指定关联的知识点节点ID")
    generate_analysis: bool = Field(True, description="是否生成AI解析")


class ParseOnlyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000, description="原始题目文本")


# ============================================================
# 端点
# ============================================================

@router.post("/quiz/import/text", status_code=201)
async def import_text(
    req: ImportTextRequest,
    db: Session = Depends(get_db),
):
    """单题文本导入：AI解析 → 关联知识点 → 生成解析 → 保存。"""
    try:
        result = await import_single(
            req.text,
            db,
            node_id=req.node_id,
            generate_analysis_flag=req.generate_analysis,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])

    return {
        "id": result["question_id"],
        "node_id": result["node_id"],
        "parsed": result["parsed"],
        "message": "导入成功",
    }


@router.post("/quiz/import/batch", status_code=201)
async def import_batch_text(
    req: ImportBatchRequest,
    db: Session = Depends(get_db),
):
    """批量文本导入：自动按题号分割为多题，逐题导入，单题失败不影响其他。"""
    # 分割题目
    questions = split_questions(req.text)
    if not questions:
        raise HTTPException(status_code=400, detail="未识别到有效题目，请检查文本格式")

    logger.info("批量导入: 识别到 %d 道题", len(questions))

    try:
        result = await import_batch(
            questions,
            db,
            node_id=req.node_id,
            generate_analysis_flag=req.generate_analysis,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e

    # 整理失败详情
    failures = []
    for i, r in enumerate(result["results"]):
        if not r["success"]:
            failures.append({
                "index": i + 1,
                "error": r["error"],
                "text_preview": questions[i][:100] if i < len(questions) else "",
            })

    return {
        "total": result["total"],
        "success": result["success"],
        "failed": result["failed"],
        "failures": failures,
        "question_ids": [r["question_id"] for r in result["results"] if r["success"]],
        "message": f"批量导入完成：成功 {result['success']}/{result['total']}",
    }


@router.post("/quiz/import/parse")
async def parse_only(
    req: ParseOnlyRequest,
    db: Session = Depends(get_db),
):
    """仅解析题目，不保存到数据库（用于预览）。"""
    try:
        parsed = await parse_question(req.text, db=db)
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 尝试匹配知识点
    matched_node = find_matching_node(parsed.get("knowledge_hint", ""), db)
    matched = None
    if matched_node:
        matched = {
            "id": matched_node.id,
            "name": matched_node.name,
            "level": matched_node.level,
        }

    return {
        "parsed": parsed,
        "matched_node": matched,
        "message": "解析完成（未保存）",
    }


@router.post("/quiz/import/analysis")
async def analysis_only(
    req: ParseOnlyRequest,
    db: Session = Depends(get_db),
):
    """仅生成题目解析，不保存（用于预览解析质量）。"""
    try:
        # 先解析
        parsed = await parse_question(req.text, db=db)
        # 再生成解析
        analysis_data = await generate_analysis(
            question=parsed["question"],
            qtype=parsed["qtype"],
            options=parsed["options"],
            correct_answer=parsed["correct_answer"],
            db=db,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}") from e

    return {
        "parsed": parsed,
        "analysis": analysis_data,
        "message": "解析生成完成（未保存）",
    }


@router.get("/quiz/import/split-preview")
async def split_preview(
    text: str = Query(..., min_length=1, max_length=50000, description="包含多道题的原始文本"),
):
    """预览题目分割结果（不调用AI，不保存）。"""
    questions = split_questions(text)
    return {
        "count": len(questions),
        "questions": [
            {"index": i + 1, "preview": q[:200], "length": len(q)}
            for i, q in enumerate(questions)
        ],
    }
