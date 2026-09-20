"""出题与判卷 API。"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import KnowledgeNode, QuizQuestion
from ..services.ai_gateway import AiGatewayError
from ..services.quiz import generate_question, grade_answer, load_payload
from ..services.quiz_contract import sanitize_for_client, ALL_QTYPES

router = APIRouter(prefix="/api/v1", tags=["quiz"])


class QuizAnswerRequest(BaseModel):
    question_id: int
    user_answer: str = Field(min_length=1, max_length=4000)


class QuizAnswerOut(BaseModel):
    question_id: int
    correct: bool | None
    score: int
    feedback: str
    standard_answer: str
    node_id: int


def _question_out(q: QuizQuestion) -> dict:
    payload = load_payload(q)
    safe = sanitize_for_client(payload)
    return {
        "id": q.id,
        "node_id": q.node_id,
        "qtype": q.qtype,
        "difficulty": q.difficulty,
        **safe,
    }


@router.post("/knowledge/nodes/{node_id}/quiz", status_code=201)
async def create_quiz(
    node_id: int,
    force_type: str | None = Query(None, description="强制题型，如 recite/single_choice/fill_cloze"),
    db: Session = Depends(get_db),
):
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="知识点不存在")
    if force_type is not None and force_type not in ALL_QTYPES:
        raise HTTPException(status_code=400, detail=f"未知题型: {force_type}，可选: {', '.join(ALL_QTYPES)}")
    try:
        q = await generate_question(db, node_id, force_type=force_type)
    except AiGatewayError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _question_out(q)


@router.post("/quiz/answer")
async def answer_quiz(payload: QuizAnswerRequest, db: Session = Depends(get_db)):
    try:
        answer = await grade_answer(db, payload.question_id, payload.user_answer)
        q = db.get(QuizQuestion, payload.question_id)
        p = load_payload(q)
        qtype = p.get("type", q.qtype)
        # 解析判卷反馈（ai_feedback 是 JSON 字符串）
        try:
            feedback_data = json.loads(answer.ai_feedback) if answer.ai_feedback else {}
        except (json.JSONDecodeError, TypeError):
            feedback_data = {}
        # 客观题判定 correct，主观题返回 None（AI 评分）
        from ..services.quiz_contract import OBJECTIVE_TYPES
        is_objective = qtype in OBJECTIVE_TYPES
        correct = (answer.score >= 100) if is_objective else None
        # 标准答案：v2.0 用 correct_answer，兼容旧 answer 字段
        standard = p.get("correct_answer", p.get("answer", ""))
        if isinstance(standard, list):
            standard = ", ".join(str(x) for x in standard)
        # 可读反馈：优先 feedback_text/ai_feedback_text，其次 explanation
        readable_feedback = (
            feedback_data.get("feedback_text")
            or feedback_data.get("ai_feedback_text")
            or feedback_data.get("feedback")
            or p.get("explanation", "")
        )
        return {
            "question_id": q.id,
            "correct": correct,
            "score": answer.score,
            "feedback": str(readable_feedback),
            "standard_answer": str(standard),
            "explanation": p.get("explanation", ""),
            "node_id": q.node_id,
            "qtype": qtype,
            "blank_results": feedback_data.get("blank_results", []),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AiGatewayError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e