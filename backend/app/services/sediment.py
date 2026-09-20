"""知识沉淀：答疑对话 → 建议提取 → 用户确认 → 知识树 + 复习队列。"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Conversation, KnowledgeNode, Message, ReviewQueue, SedimentSuggestion
from ..models.enums import NodeStatus, ReviewStatus, SedimentKind, SedimentStatus, Source
import time

from .call_logger import set_function_type
from .ai_gateway import chat_once
from . import experiment_service

INITIAL_REVIEW_DELAY_DAYS = 1  # FSRS 新卡首答间隔（学习步）



def _build_sediment_messages_v1(messages: list[Message]) -> list[dict]:
    """旧版 v1：单 user + 完整 JSON 数组示例（A/B 对照组）。

    与 v2（_build_sediment_messages）对比：
    - v1: 单 user 消息，角色+规则+完整JSON数组示例+对话文本全部混在一起
    - v2: system+user 分离，字段定义表代替完整示例，预计节省 token 40%
    """
    transcript = "\n".join(f"{m.role}: {m.content[:300]}" for m in messages)
    prompt = (
        "你是学习内容整理助手。从下面这份学习对话中提取值得沉淀的知识点，"
        "只提取有长期价值的（新概念、纠正过的错误认知、可复用的结论/口诀）。\n"
        '返回严格 JSON 数组（最多 5 条，没有则返回 []）：'
        '[{"kind":"concept|correction|conclusion","name":"知识点名称(<=20字)",'
        '"content":"要记录的内容(<=60字，用一句完整的陈述句)"}]\n\n'
        f"对话：\n{transcript[:4000]}"
    )
    return [{"role": "user", "content": prompt}]


def _build_sediment_messages(messages: list[Message]) -> list[dict]:
    """构建知识沉淀提取的 messages（system+user 分离 + 字段定义表）。

    优化策略：
    - system: 角色 + 字段定义表（代替完整JSON数组示例） + 合并规则段
    - user: 仅对话文本 JSON
    - transcript 截断从 4000 字收紧到 3000 字（sediment 只需关键信息）
    - 预计节省 prompt token 约 40%
    """
    system_content = (
        "你是学习内容整理助手。从学习对话中提取有长期价值的知识点。\n"
        "输出严格 JSON 数组，不要任何其他文字。\n\n"
        "字段定义：\n"
        "- kind: enum(concept|correction|conclusion) 类型\n"
        "- name: string 知识点名(<=20字)\n"
        "- content: string 记录内容(<=60字，完整陈述句)\n\n"
        "规则：\n"
        "- 只提取新概念、纠正过的错误认知、可复用的结论/口诀\n"
        "- 最多 5 条\n"
        "- 没有值得沉淀的内容时返回 []"
    )

    transcript = "\n".join(f"{m.role}: {m.content[:300]}" for m in messages)
    user_data = {"transcript": transcript[:3000]}

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_data, ensure_ascii=False)},
    ]


async def generate_suggestions(db: Session, conversation_id: int) -> list[SedimentSuggestion]:
    """从对话中提取沉淀建议（概念/纠错/结论），落库 pending。"""
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError(f"会话不存在: {conversation_id}")
    # 检查是否已生成过
    existing = db.scalar(
        select(SedimentSuggestion.id)
        .where(SedimentSuggestion.conversation_id == conversation_id)
        .limit(1)
    )
    if existing:
        return list(
            db.scalars(
                select(SedimentSuggestion).where(
                    SedimentSuggestion.conversation_id == conversation_id
                )
            )
        )

    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
            .limit(30)
        )
    )
    if not messages:
        return []

    # A/B 实验分桶
    _exp = experiment_service.get_experiment(db, "sediment_prompt_v2")
    _variant = experiment_service.assign_variant(_exp, f"conv_{conv.id}") if _exp else None
    _exp_start = time.monotonic()

    if _variant == "control":
        llm_messages = _build_sediment_messages_v1(messages)
    else:
        llm_messages = _build_sediment_messages(messages)

    try:
        set_function_type("sediment")
        raw = await chat_once(llm_messages, temperature=0.3)
    except Exception:
        if _exp and _variant:
            _exp_duration = int((time.monotonic() - _exp_start) * 1000)
            experiment_service.record_event(_exp, _variant, f"conv_{conv.id}", "sediment", {
                "format_valid": False,
                "duration_ms": _exp_duration,
            })
        return []
    try:
        items = json.loads(raw.strip())
        if not isinstance(items, list):
            items = []
    except json.JSONDecodeError:
        items = []

    # 记录实验事件
    if _exp and _variant:
        _exp_duration = int((time.monotonic() - _exp_start) * 1000)
        experiment_service.record_event(_exp, _variant, f"conv_{conv.id}", "sediment", {
            "format_valid": bool(items),
            "duration_ms": _exp_duration,
        })

    if not items:
        return []
    for it in items[:5]:
        kind = it.get("kind", "conclusion")
        if kind not in (SedimentKind.CONCEPT, SedimentKind.CORRECTION, SedimentKind.CONCLUSION):
            kind = SedimentKind.CONCLUSION
        db.add(
            SedimentSuggestion(
                conversation_id=conv.id,
                kind=kind,
                content=str(it.get("content", ""))[:200],
                status=SedimentStatus.PENDING,
            )
        )
    db.commit()
    return list(
        db.scalars(
            select(SedimentSuggestion).where(
                SedimentSuggestion.conversation_id == conversation_id
            )
        )
    )


def accept_suggestion(db: Session, suggestion_id: int) -> KnowledgeNode:
    """确认沉淀：写入知识树（同名节点合并）+ 排入复习队列。"""
    sug = db.get(SedimentSuggestion, suggestion_id)
    if not sug:
        raise ValueError(f"沉淀建议不存在: {suggestion_id}")
    sug.status = SedimentStatus.ACCEPTED

    # 找到所属会话对应的科目（会话 → 课程 → 科目 id）
    conv = db.get(Conversation, sug.conversation_id)
    subject_id = None
    if conv and conv.session_id:
        from ..models import StudySession

        ss = db.get(StudySession, conv.session_id)
        if ss:
            subject_id = ss.course_id

    # 同名节点合并（概念类建议避免重复建点）
    node = db.scalar(select(KnowledgeNode).where(KnowledgeNode.name == sug.content[:20]))
    if node is None:
        node = KnowledgeNode(
            parent_id=None if not subject_id else _find_or_create_misc_parent(db, subject_id),
            subject_id=subject_id,
            name=sug.content[:40],
            level=3,
            difficulty=2,
            source=Source.QA_SEDIMENT,
            status=NodeStatus.UNTOUCHED,
            summary=sug.content,
        )
        db.add(node)
        db.flush()
    else:
        node.summary = (node.summary or "") + "\n" + sug.content if node.summary else sug.content

    # 复习队列：FSRS 新卡（学习步 1 天），后续到期节奏由评分档位驱动
    db.add(
        ReviewQueue(
            node_id=node.id,
            due_at=datetime.now() + timedelta(days=INITIAL_REVIEW_DELAY_DAYS),
            status=ReviewStatus.OPEN,
            source="sediment",
            fsrs_d=5.0,
            fsrs_s=None,
            fsrs_state="learning",
            fsrs_step=0,
            reps=0,
            lapses=0,
        )
    )
    db.commit()
    db.refresh(node)
    return node


def _find_or_create_misc_parent(db: Session, subject_id: int) -> int | None:
    """找（或建）"答疑沉淀"收纳节点，避免根上堆叶子。"""
    root = db.scalar(
        select(KnowledgeNode).where(
            KnowledgeNode.subject_id == subject_id,
            KnowledgeNode.parent_id.is_(None),
            KnowledgeNode.name == "答疑沉淀",
        )
    )
    if root:
        return root.id
    root = KnowledgeNode(
        parent_id=None,
        subject_id=subject_id,
        name="答疑沉淀",
        level=1,
        source=Source.MANUAL,
        status=NodeStatus.UNTOUCHED,
    )
    db.add(root)
    db.flush()
    return root.id


def reject_suggestion(db: Session, suggestion_id: int) -> None:
    sug = db.get(SedimentSuggestion, suggestion_id)
    if sug:
        sug.status = SedimentStatus.REJECTED
        db.commit()
