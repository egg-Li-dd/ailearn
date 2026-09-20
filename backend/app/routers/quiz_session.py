"""测验会话 API（批量出题/统一提交/重做）。

端点：
- POST /api/v1/quiz-sessions          创建会话（批量出题）
- GET  /api/v1/quiz-sessions/{id}     获取会话状态+题目
- POST /api/v1/quiz-sessions/{id}/submit  统一提交答案（纠错）
- POST /api/v1/quiz-sessions/{id}/redo    重做（一键/单题）
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Conversation, QuizSession
from ..services.ai_gateway import AiGatewayError
from ..services.quiz_session import (
    create_session, get_active_session, redo_session,
    save_draft_answer,
    session_to_client_response, submit_answers,
)

logger = logging.getLogger("ailearn.quiz_session_api")
router = APIRouter(prefix="/api/v1/quiz-sessions", tags=["quiz_session"])


# ---------- 请求模型 ----------

class CreateSessionRequest(BaseModel):
    session_type: str = Field(default="class_break", pattern="^(single|batch|class_break)$")
    title: str | None = Field(default=None, max_length=200)
    question_count: int = Field(default=5, ge=1, le=20)
    node_ids: list[int] | None = None
    question_types: list[str] | None = None


class SubmitAnswerItem(BaseModel):
    question_id: int
    user_answer: object = None  # 多空填空=dict，单选=int，简答=str


class SubmitRequest(BaseModel):
    answers: list[SubmitAnswerItem] = Field(min_length=1)


class RedoRequest(BaseModel):
    question_ids: list[int] | None = None  # None/空=全部重做


class DraftAnswerRequest(BaseModel):
    question_id: int
    user_answer: str = ""  # 空字符串表示清空该题草稿


# ---------- 辅助 ----------

def _get_classroom_conv(db: Session) -> Conversation:
    """获取当前课堂会话（单用户模式下取最新的 classroom 对话）。"""
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.mode == "classroom")
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="课堂会话不存在，请先进入课堂")
    return conv


# ---------- 端点 ----------

@router.post("", status_code=201)
async def create_session_endpoint(payload: CreateSessionRequest, db: Session = Depends(get_db)):
    """创建测验会话并批量出题（多题同屏）。"""
    conv = _get_classroom_conv(db)
    try:
        session = await create_session(
            db, conv,
            session_type=payload.session_type,
            title=payload.title,
            question_count=payload.question_count,
            node_ids=payload.node_ids,
            question_types=payload.question_types,
        )
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 出题失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return session_to_client_response(db, session)


@router.get("/{session_id}")
def get_session_endpoint(session_id: int, db: Session = Depends(get_db)):
    """获取会话状态+题目（脱敏）。"""
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="测验会话不存在")
    return session_to_client_response(db, session)


@router.post("/{session_id}/submit")
async def submit_endpoint(session_id: int, payload: SubmitRequest, db: Session = Depends(get_db)):
    """统一提交答案并逐题判卷（统一纠错）。"""
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="测验会话不存在")

    answers = [a.model_dump() for a in payload.answers]
    try:
        result = await submit_answers(db, session, answers)
    except AiGatewayError as e:
        raise HTTPException(status_code=502, detail=f"AI 判卷失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return result


@router.post("/{session_id}/redo")
def redo_endpoint(session_id: int, payload: RedoRequest, db: Session = Depends(get_db)):
    """重做（一键重做全部或单题重做）。

    题目和静态解析从 DB 复用，不重新生成；只重置作答状态。
    """
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="测验会话不存在")

    try:
        result = redo_session(db, session, question_ids=payload.question_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return result


@router.post("/{session_id}/draft")
def save_draft_endpoint(session_id: int, payload: DraftAnswerRequest, db: Session = Depends(get_db)):
    """保存单题草稿答案（答题过程中实时保存，刷新后可恢复）。

    user_answer 为空字符串时表示清空该题草稿。
    """
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="测验会话不存在")
    if session.status != "awaiting_submit":
        raise HTTPException(status_code=400, detail=f"当前状态({session.status})不允许保存草稿")

    save_draft_answer(db, session_id, payload.question_id, payload.user_answer)
    return {"saved": True, "question_id": payload.question_id}


@router.get("")
def list_active_session(db: Session = Depends(get_db)):
    """获取当前活跃的测验会话（如果有）。"""
    conv = _get_classroom_conv(db)
    session = get_active_session(db, conv)
    if not session:
        return {"exists": False}
    return {"exists": True, **session_to_client_response(db, session)}
