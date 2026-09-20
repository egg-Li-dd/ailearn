"""知识库 Pydantic 模型。"""
from datetime import datetime

from pydantic import BaseModel, Field


class NodeCreate(BaseModel):
    parent_id: int | None = None
    subject_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    difficulty: int = Field(default=1, ge=1, le=5)
    summary: str | None = Field(default=None, max_length=2000)
    sort: int = 0
    icon: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    prerequisites: str | None = None


class NodeUpdate(BaseModel):
    parent_id: int | None = None
    subject_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    summary: str | None = Field(default=None, max_length=2000)
    mastery: int | None = Field(default=None, ge=0, le=100)
    source: str | None = Field(default=None, max_length=16)
    sort: int | None = None
    icon: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    prerequisites: str | None = None


class NodeOut(BaseModel):
    id: int
    parent_id: int | None
    subject_id: int | None
    name: str
    level: int
    difficulty: int
    mastery: int
    status: str
    source: str
    summary: str | None
    sort: int = 0
    icon: str | None = None
    notes: str | None = None
    prerequisites: str | None = None
    question_count: int = 0
    children: list["NodeOut"] = []

    model_config = {"from_attributes": True}


class NodeDetailOut(BaseModel):
    """节点完整详情。"""
    id: int
    parent_id: int | None
    subject_id: int | None
    name: str
    level: int
    difficulty: int
    mastery: int
    status: str
    icon: str | None
    summary: str | None
    notes: str | None
    sort: int
    question_count: int = 0
    prerequisites: list[dict] = []
    successors: list[dict] = []
    mastery_history: list[dict] = []
    questions: list[dict] = []


class NodeMoveRequest(BaseModel):
    """拖拽移动节点。"""
    parent_id: int | None = None
    sort: int = 0


class NodeSortItem(BaseModel):
    id: int
    sort: int


class NodeBatchDelete(BaseModel):
    ids: list[int]


class PrerequisitesUpdate(BaseModel):
    ids: list[int]


class ImportOutlineRequest(BaseModel):
    subject_id: int
    text: str = Field(min_length=10, max_length=20000)


class ImportPreviewOut(BaseModel):
    """AI 大纲导入预览（不写入 DB）。"""
    preview_id: str
    items: list[dict]
    total_nodes: int


class ImportConfirmRequest(BaseModel):
    preview_id: str
    subject_id: int


class CopySubtreeRequest(BaseModel):
    target_subject_id: int


class MasteryUpdateRequest(BaseModel):
    """外部掌握度更新（答题得分/自评）。"""
    value: float = Field(ge=0, le=100)
    reason: str | None = Field(default=None, max_length=128)
    source: str = Field(default="self_report", max_length=16)


class MasteryHistoryOut(BaseModel):
    node_id: int
    records: list[dict]


# 解决前向引用
NodeOut.model_rebuild()
