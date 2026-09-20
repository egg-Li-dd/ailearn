"""答疑会话与 SSE 流式消息 API。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_db, utcnow
from ..models import Conversation, Message
from ..schemas.chat import ConversationCreate, ConversationOut, MessageCreate, MessageOut
from ..services.ai_gateway import AiGatewayError
from ..services.sediment import generate_suggestions
from ..services.tutor import stream_tutor_reply

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _get_conversation_or_404(db: Session, conversation_id: int) -> Conversation:
    c = db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(status_code=404, detail="会话不存在")
    return c


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    return list(
        db.scalars(select(Conversation).order_by(Conversation.started_at.desc()).limit(50))
    )


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    conv = Conversation(mode=payload.mode, session_id=payload.session_id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    _get_conversation_or_404(db, conversation_id)
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
    )


@router.post("/conversations/{conversation_id}/sediments")
async def generate_sediments(conversation_id: int, db: Session = Depends(get_db)):
    """从对话提取沉淀建议（AI）。"""
    _get_conversation_or_404(db, conversation_id)
    try:
        items = await generate_suggestions(db, conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AiGatewayError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return [
        {"id": s.id, "kind": s.kind, "content": s.content, "status": s.status}
        for s in items
    ]


@router.post("/sediments/{suggestion_id}/accept", status_code=201)
def accept_sediment(suggestion_id: int, db: Session = Depends(get_db)):
    from ..services.sediment import accept_suggestion

    try:
        node = accept_suggestion(db, suggestion_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"node_id": node.id, "node_name": node.name}


@router.post("/sediments/{suggestion_id}/reject")
def reject_sediment(suggestion_id: int, db: Session = Depends(get_db)):
    from ..services.sediment import reject_suggestion

    reject_suggestion(db, suggestion_id)
    return {"ok": True}


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, payload: MessageCreate):
    """发送消息 → SSE 流式返回教练回答（流内独立 db 生命周期）。"""
    db = SessionLocal()
    try:
        conv = _get_conversation_or_404(db, conversation_id)
        db.add(Message(conversation_id=conv.id, role="user", content=payload.content))
        db.commit()

        history = [
            {"role": m.role, "content": m.content}
            for m in db.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.id)
                .limit(20)
            )
        ]

        async def generate():
            try:
                async for ev in stream_tutor_reply(
                    db, history[:-1], payload.content, mode=conv.mode
                ):
                    if ev["type"] == "done":
                        db.add(
                            Message(
                                conversation_id=conv.id,
                                role="assistant",
                                content=ev["text"],
                                ref_knowledge_ids=json.dumps(ev["knowledge_ids"]),
                            )
                        )
                        db.commit()
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            except AiGatewayError as e:
                yield (
                    f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                )
            except Exception as e:
                yield (
                    f"data: {json.dumps({'type': 'error', 'message': f'服务异常：{e}'}, ensure_ascii=False)}\n\n"
                )
            finally:
                db.close()  # 流结束，关闭会话（该 db 由本请求独占）

        return StreamingResponse(generate(), media_type="text/event-stream")
    except HTTPException:
        db.close()
        raise
    finally:
        pass  # 正常路径由 generate 的 finally 关闭