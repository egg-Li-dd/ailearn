"""答疑 Agent：prompt 构建 + RAG 检索 + 软标注提取。

软标注协议：AI 在回答中以 [[知识点名]] 标记涉及的知识点；
后端解析标记 → 匹配知识库节点（存 ref_knowledge_ids），
文本保留标记供前端渲染为可点击 chip。
"""
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode
from .ai_gateway import chat_stream
from .call_logger import set_function_type, reset_function_type

COACH_SYSTEM = (
    "你是 ai学 的学习教练，陪伴用户完成计算机考研等科目的学习。"
    "你讲话认真、直接、有判断力，不啰嗦，一次回答聚焦一个问题。"
    "回答中用短句和例子，必要时给口诀或对比表。"
    "如果用户问的内容涉及具体知识点，用 [[知识点名称]] 标记它（每个知识点一次即可）。"
    "标记名称必须精确，不要自创名称；若与下方知识库节点名匹配，优先使用节点名。"
    "不要为标记而标记：只有确实讲到知识点时才标记，一次回答不超过 5 个标记。"
)

KNOWLEDGE_LABEL_REGEX = re.compile(r"\[\[([^\[\]]+)\]\]")


def build_session_messages(
    db: Session,
    history: list[dict],
    user_input: str,
    *,
    mode: str = "free",
) -> list[dict]:
    """组装发送给 LLM 的消息（含 RAG 上下文）。"""
    messages: list[dict] = [{"role": "system", "content": COACH_SYSTEM}]

    rag = _rag_context(db, user_input, limit=4)
    if rag:
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下是用户知识库中相关的既有知识（回答时优先引用并衔接，不要复制粘贴整段）：\n"
                    + rag
                ),
            }
        )

    if mode == "mini_test":
        messages.append(
            {
                "role": "system",
                "content": (
                    "当前处于小测模式：请输出 5 道快速测试题（选择或填空），"
                    "考察用户最近学习的薄弱知识点，题目难度循序渐进。"
                    "每道题标注 [[知识点]]。"
                ),
            }
        )
    elif mode == "quiz":
        messages.append(
            {
                "role": "system",
                "content": "当前处于做题模式：配合用户选择的知识点出题，先出 1 题，作答后再出下一题。",
            }
        )

    messages.extend(history[-10:])  # 单次会话保留最近 10 轮上下文
    messages.append({"role": "user", "content": user_input})
    return messages


def _rag_context(db: Session, query: str, limit: int = 4) -> str:
    """按查询词在知识库节点名中检索，返回上下文文本（无命中返回空串）。"""
    keywords = [k.strip() for k in re.split(r"[\s,，。？?！!、/]+", query) if len(k.strip()) >= 2]
    if not keywords:
        return ""
    hits: dict[int, KnowledgeNode] = {}
    for kw in keywords:
        rows = db.scalars(
            select(KnowledgeNode)
            .where(KnowledgeNode.name.contains(kw), KnowledgeNode.level >= 3)
            .limit(limit)
        )
        for n in rows:
            hits[n.id] = n
        if len(hits) >= limit:
            break
    if not hits:
        return ""
    lines = []
    for n in list(hits.values())[:limit]:
        summary = n.summary or ""
        lines.append(f"- {n.name}（难度 {n.difficulty}）{(': ' + summary) if summary else ''}")
    return "\n".join(lines)


def parse_knowledge_labels(text: str) -> list[str]:
    """解析 [[xxx]] 标记，返回知识点名称列表（去除重复）。"""
    seen: list[str] = []
    for m in KNOWLEDGE_LABEL_REGEX.finditer(text):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def resolve_knowledge_ids(db: Session, names: Iterable[str]) -> list[int]:
    """按名称精确匹配知识库节点，返回 id 列表（未命中跳过）。"""
    ids: list[int] = []
    for name in names:
        node = db.scalar(select(KnowledgeNode).where(KnowledgeNode.name == name))
        if node:
            ids.append(node.id)
    return ids


async def stream_tutor_reply(
    db: Session,
    history: list[dict],
    user_input: str,
    *,
    mode: str = "free",
):
    """流式生成教练回答：逐段产出文本；结束时产出 (full_text, knowledge_ids)。"""
    messages = build_session_messages(db, history, user_input, mode=mode)
    parts: list[str] = []
    ft_token = set_function_type("tutor")
    try:
        async for text in chat_stream(messages):
            parts.append(text)
            yield {"type": "chunk", "text": text}
    finally:
        reset_function_type(ft_token)
    full = "".join(parts)
    names = parse_knowledge_labels(full)
    ids = resolve_knowledge_ids(db, names)
    yield {"type": "done", "text": full, "knowledge_ids": ids, "knowledge_names": names}