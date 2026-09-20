"""答疑会话 Pydantic 模型。"""
from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    mode: str = Field(default="free", pattern="^(free|quiz|mini_test)$")
    session_id: int | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    ref_knowledge_ids: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    session_id: int | None
    mode: str
    started_at: datetime

    model_config = {"from_attributes": True}