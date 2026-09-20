"""课堂 API：状态接入（前端零状态）+ 互动（SSE 块流）。

v2 改动：按 course_id 隔离 Conversation，每个科目独立历史；
支持手动切换科目 + in_class 自动跳转（手动锁定本节课内有效）；
历史消息按保留天数自动清理。
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_db
from ..models import Conversation, Course, KnowledgeNode, Message, StudySession, UserSetting
from ..services.call_logger import set_function_type
from ..services.ai_gateway import AiGatewayError
from ..services.classroom import interact

logger = logging.getLogger("ailearn.classroom")

router = APIRouter(prefix="/api/v1/classroom", tags=["classroom"])

DEFAULT_RETENTION_DAYS = 30

# ---------- 请求模型 ----------


class InteractRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    question_id: int | None = Field(default=None, description="作答模式：当前回答的题目ID，用于判卷反馈精准关联")


class ActivateRequest(BaseModel):
    session_id: int


class SwitchRequest(BaseModel):
    course_id: int


class RetentionRequest(BaseModel):
    days: int = Field(ge=1, le=365)


# ---------- 辅助函数 ----------


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(UserSetting, key)
    return row.value if row else default


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(UserSetting, key)
    if row:
        row.value = value
    else:
        db.add(UserSetting(key=key, value=value))
    db.commit()


def _get_retention_days(db: Session) -> int:
    raw = _get_setting(db, "classroom_retention_days", str(DEFAULT_RETENTION_DAYS))
    try:
        return max(1, min(365, int(raw)))
    except (ValueError, TypeError):
        return DEFAULT_RETENTION_DAYS


def _get_in_class_session(db: Session) -> StudySession | None:
    return db.scalar(
        select(StudySession).where(StudySession.status == "in_class").limit(1)
    )


def _resolve_active_course_id(db: Session) -> tuple[int | None, bool]:
    """解析当前应激活的科目。

    返回 (course_id, is_manual_locked)。
    规则：
    1. 读手动锁定：classroom_manual_course_id + classroom_manual_locked_session_id
    2. 查当前 in_class 会话
    3. 有手动锁定 且 锁定时的 in_class session == 当前 in_class session → 用手动锁定
    4. 否则（无锁定 / 是新课）→ 清除锁定，用当前 in_class 的 course_id
    5. 都没有 in_class → 用手动锁定的（如果有），否则 None
    """
    manual_course_raw = _get_setting(db, "classroom_manual_course_id", "")
    manual_locked_sid_raw = _get_setting(db, "classroom_manual_locked_session_id", "")

    manual_course_id = None
    if manual_course_raw:
        try:
            manual_course_id = int(manual_course_raw)
        except (ValueError, TypeError):
            manual_course_id = None

    manual_locked_sid = None
    if manual_locked_sid_raw:
        try:
            manual_locked_sid = int(manual_locked_sid_raw)
        except (ValueError, TypeError):
            manual_locked_sid = None

    in_class = _get_in_class_session(db)
    in_class_sid = in_class.id if in_class else None

    # 有手动锁定 且 锁定时的 in_class 会话与当前一致 → 保持手动锁定
    if manual_course_id is not None and manual_locked_sid == in_class_sid:
        # 验证科目存在
        if db.get(Course, manual_course_id):
            return manual_course_id, True

    # 否则清除手动锁定（如果是因为新课导致的）
    if manual_course_id is not None and in_class_sid is not None and manual_locked_sid != in_class_sid:
        _set_setting(db, "classroom_manual_course_id", "")
        _set_setting(db, "classroom_manual_locked_session_id", "")

    # 有 in_class → 自动用其科目
    if in_class is not None:
        return in_class.course_id, False

    # 没有 in_class 但有手动锁定（之前在无课状态下手动选的）→ 保持
    if manual_course_id is not None and db.get(Course, manual_course_id):
        return manual_course_id, True

    return None, False


def _get_or_create_conversation(db: Session, course_id: int | None) -> Conversation:
    """按 course_id 找或创建课堂 Conversation。

    course_id 为 None 时，回退到旧逻辑（取最新的 classroom conversation）。
    """
    if course_id is None:
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.mode == "classroom")
            .order_by(Conversation.id.desc())
            .limit(1)
        )
        if conv is None:
            conv = Conversation(mode="classroom", session_id=None, course_id=None)
            db.add(conv)
            db.commit()
            db.refresh(conv)
        return conv

    conv = db.scalar(
        select(Conversation)
        .where(Conversation.mode == "classroom", Conversation.course_id == course_id)
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    if conv is None:
        conv = Conversation(mode="classroom", session_id=None, course_id=course_id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def _cleanup_old_messages(db: Session, conversation_id: int, retention_days: int) -> int:
    """清理指定 conversation 中超过保留天数的消息，返回删除条数。"""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    result = db.execute(
        delete(Message).where(
            Message.conversation_id == conversation_id,
            Message.created_at < cutoff,
        )
    )
    db.commit()
    return result.rowcount or 0


def _auto_bind_session(db: Session, conv: Conversation, course_id: int | None) -> None:
    """如果 conversation 没有绑定 session 且当前 in_class 匹配该科目，自动绑定。"""
    if conv.session_id is not None:
        return
    if course_id is None:
        return
    in_class = _get_in_class_session(db)
    if in_class is not None and in_class.course_id == course_id:
        conv.session_id = in_class.id
        db.commit()


def _blocks_of(db: Session, conv: Conversation) -> list[dict]:
    """消息 → 前端块视图（历史课堂流）。"""
    msgs = list(
        db.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)
        )
    )
    blocks: list[dict] = []
    for m in msgs:
        if m.type == "quiz":
            try:
                payload = json.loads(m.content)
            except json.JSONDecodeError:
                continue
            node_id = payload.get("_node_id")
            qtype = payload.get("qtype", payload.get("question_type", "choice"))
            blk = {
                "kind": "quiz",
                "id": payload.get("_quiz_id"),
                "block_id": m.id,
                "qtype": qtype,
                "question": payload.get("question", ""),
                "options": payload.get("options", []),
                "node_id": node_id,
            }
            if qtype in ("short", "code"):
                blk["reference_answer"] = payload.get("correct_answer", "")
                blk["points"] = payload.get("points", 3)
            if qtype == "fill_cloze":
                blk["blanks"] = [
                    {"id": b.get("id"), "hint": b.get("hint")}
                    for b in (payload.get("blanks") or [])
                    if isinstance(b, dict)
                ]
            blk["ai_usage"] = {
                "model": m.ai_model,
                "channel": m.ai_channel,
                "prompt_tokens": m.ai_prompt_tokens,
                "completion_tokens": m.ai_completion_tokens,
                "total_tokens": m.ai_total_tokens,
                "cost": m.ai_cost,
                "duration_ms": m.ai_duration_ms,
            }
            blocks.append(blk)
        elif m.type == "quiz_session":
            payload = None
            try:
                payload = json.loads(m.content)
            except json.JSONDecodeError:
                payload = None
            sid = (payload or {}).get("session_id") or (payload or {}).get("id")
            if sid is not None:
                blocks.append({
                    "kind": "quiz_session",
                    "session_id": sid,
                    "count": (payload or {}).get("count", 0),
                    "message": None,
                })
            else:
                blocks.append({"kind": "text", "role": m.role, "content": m.content})
        elif m.type == "feedback":
            try:
                fb = json.loads(m.content)
            except (json.JSONDecodeError, TypeError):
                blocks.append({"kind": "text", "role": m.role, "content": m.content})
                continue
            if fb.get("question_id") is None:
                continue
            qid = fb["question_id"]
            merged = False
            for blk in blocks:
                if blk.get("kind") == "quiz" and blk.get("id") == qid:
                    blk["grade_result"] = fb
                    merged = True
                    break
            if not merged:
                blocks.append({"kind": "feedback", **fb})
        elif m.type == "cloze_batch":
            try:
                payload = json.loads(m.content)
            except json.JSONDecodeError:
                continue
            blocks.append({
                "kind": "cloze_batch",
                "block_id": m.id,
                "clozes": payload.get("clozes", []),
                "selected_nodes": payload.get("selected_nodes", []),
                "task_id": payload.get("task_id"),
                "ai_usage": {
                    "model": m.ai_model,
                    "channel": m.ai_channel,
                    "prompt_tokens": m.ai_prompt_tokens,
                    "completion_tokens": m.ai_completion_tokens,
                    "total_tokens": m.ai_total_tokens,
                    "cost": m.ai_cost,
                    "duration_ms": m.ai_duration_ms,
                },
            })
        elif m.type == "cloze_feedback":
            try:
                fb = json.loads(m.content)
            except (json.JSONDecodeError, TypeError):
                continue
            # 合并到最近一个未评分的 cloze_batch block
            merged = False
            for blk in reversed(blocks):
                if blk.get("kind") == "cloze_batch" and "grade_results" not in blk:
                    blk["grade_results"] = fb.get("results", [])
                    blk["grade_average"] = fb.get("average_score")
                    blk["grade_all_passed"] = fb.get("all_passed")
                    blk["grade_ai_usage"] = {
                        "model": m.ai_model,
                        "channel": m.ai_channel,
                        "prompt_tokens": m.ai_prompt_tokens,
                        "completion_tokens": m.ai_completion_tokens,
                        "total_tokens": m.ai_total_tokens,
                        "cost": m.ai_cost,
                        "duration_ms": m.ai_duration_ms,
                    }
                    merged = True
                    break
            if not merged:
                blocks.append({"kind": "cloze_feedback", **fb})
        else:
            blocks.append({"kind": "text", "role": m.role, "content": m.content})
    return blocks


# ---------- API 端点 ----------


@router.post("/activate")
def activate(payload: ActivateRequest, db: Session = Depends(get_db)):
    """任务卡深链：把课堂绑定到指定学习会话（课程上下文激活）。

    v2：按目标 session 的 course_id 找/建独立 Conversation。
    """
    ss = db.get(StudySession, payload.session_id)
    if not ss:
        raise HTTPException(status_code=404, detail="会话不存在")

    course_id = ss.course_id
    conv = _get_or_create_conversation(db, course_id)

    # 课程切换：快照旧课程记忆容器
    if conv.session_id is not None and conv.session_id != ss.id:
        old_ss = db.get(StudySession, conv.session_id)
        if old_ss and old_ss.course_id:
            from ..services.course_memory import snapshot_from_conversation
            snapshot_from_conversation(db, conv, old_ss.course_id)

    conv.session_id = ss.id
    conv.active_quiz_id = None
    ml = json.loads(conv.mainline_json) if conv.mainline_json else {}
    ml.pop("batch", None)
    ml.pop("active_task_id", None)  # 切换会话时清除旧任务上下文
    conv.mainline_json = json.dumps(ml, ensure_ascii=False)

    # 激活会话：将目标会话置为 in_class，其他 in_class 会话退回 scheduled
    # （确保 /classroom/state 的 _resolve_active_course_id 能正确解析到本节课）
    if ss.status != "in_class":
        other_in_class = db.scalars(
            select(StudySession).where(
                StudySession.status == "in_class",
                StudySession.id != ss.id,
            )
        ).all()
        for other in other_in_class:
            if other.status != "done":
                other.status = "scheduled"
        ss.status = "in_class"

    db.commit()

    course = db.get(Course, course_id)
    return {
        "conversation_id": conv.id,
        "session_id": ss.id,
        "course_id": course_id,
        "course_name": course.name if course else None,
    }


@router.post("/switch")
def switch_course(payload: SwitchRequest, db: Session = Depends(get_db)):
    """手动切换课堂科目。

    写入手动锁定（绑定当前 in_class session_id），
    按目标 course_id 找/建独立 Conversation，返回其状态。
    """
    course = db.get(Course, payload.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="科目不存在")

    # 写入手动锁定
    in_class = _get_in_class_session(db)
    _set_setting(db, "classroom_manual_course_id", str(course.id))
    _set_setting(db, "classroom_manual_locked_session_id", str(in_class.id) if in_class else "")

    conv = _get_or_create_conversation(db, course.id)
    _auto_bind_session(db, conv, course.id)

    # 清理过期历史
    retention = _get_retention_days(db)
    _cleanup_old_messages(db, conv.id, retention)

    course_name = course.name
    session_id = conv.session_id
    opening = None
    if session_id is not None:
        ss = db.get(StudySession, session_id)
        if ss and ss.course_id:
            from ..services.course_memory import build_opening, format_opening_text
            opening_data = build_opening(db, ss.course_id)
            opening = {
                "text": format_opening_text(opening_data),
                "weak_nodes": opening_data["weak_nodes"],
                "due_reviews": opening_data["due_reviews"],
                "last_knowledge": opening_data["last_knowledge"],
                "pending_quiz_id": opening_data["pending_quiz_id"],
                "mainline_valid": opening_data["mainline_valid"],
            }

    blocks = _blocks_of(db, conv)
    if conv.active_quiz_session_id:
        from ..models import QuizSession
        active_qs = db.get(QuizSession, conv.active_quiz_session_id)
        if active_qs:
            seen = any(
                b.get("kind") == "quiz_session"
                and b.get("session_id") == active_qs.id
                for b in blocks
            )
            if not seen:
                blocks.insert(0, {
                    "kind": "quiz_session",
                    "session_id": active_qs.id,
                    "count": None,
                    "message": "上次的小测还未提交，继续作答：",
                })

    return {
        "exists": True,
        "conversation_id": conv.id,
        "mode": conv.mode,
        "session_id": session_id,
        "course_id": course.id,
        "course_name": course_name,
        "is_manual_locked": True,
        "active_quiz_id": conv.active_quiz_id,
        "active_quiz_session_id": conv.active_quiz_session_id,
        "blocks": blocks,
        "opening": opening,
    }


@router.get("/state")
def classroom_state(db: Session = Depends(get_db)):
    """课堂当前状态（前端进入/重连时拉取）。

    v2：按 course_id 隔离，自动解析当前科目（手动锁定优先 / in_class 自动跳转）。
    """
    course_id, is_manual = _resolve_active_course_id(db)

    if course_id is None:
        return {"exists": False, "course_id": None, "course_name": None, "is_manual_locked": False}

    conv = _get_or_create_conversation(db, course_id)
    _auto_bind_session(db, conv, course_id)

    # 清理过期历史（懒清理，每次进入时执行）
    retention = _get_retention_days(db)
    deleted = _cleanup_old_messages(db, conv.id, retention)
    if deleted:
        logger.info("classroom %d: cleaned %d old messages (retention=%dd)", conv.id, deleted, retention)

    course_name = None
    session_id = conv.session_id
    if session_id is not None:
        ss = db.get(StudySession, session_id)
        if ss:
            c = db.get(Course, ss.course_id)
            course_name = c.name if c else None
    if course_name is None:
        c = db.get(Course, course_id)
        course_name = c.name if c else None

    opening = None
    if session_id is not None:
        ss = db.get(StudySession, session_id)
        if ss and ss.course_id:
            from ..services.course_memory import build_opening, format_opening_text
            opening_data = build_opening(db, ss.course_id)
            opening = {
                "text": format_opening_text(opening_data),
                "weak_nodes": opening_data["weak_nodes"],
                "due_reviews": opening_data["due_reviews"],
                "last_knowledge": opening_data["last_knowledge"],
                "pending_quiz_id": opening_data["pending_quiz_id"],
                "mainline_valid": opening_data["mainline_valid"],
            }

    blocks = _blocks_of(db, conv)
    if conv.active_quiz_session_id:
        from ..models import QuizSession
        active_qs = db.get(QuizSession, conv.active_quiz_session_id)
        if active_qs:
            seen = any(
                b.get("kind") == "quiz_session"
                and b.get("session_id") == active_qs.id
                for b in blocks
            )
            if not seen:
                blocks.insert(0, {
                    "kind": "quiz_session",
                    "session_id": active_qs.id,
                    "count": None,
                    "message": "上次的小测还未提交，继续作答：",
                })

    return {
        "exists": True,
        "conversation_id": conv.id,
        "mode": conv.mode,
        "session_id": session_id,
        "course_id": course_id,
        "course_name": course_name,
        "is_manual_locked": is_manual,
        "active_quiz_id": conv.active_quiz_id,
        "active_quiz_session_id": conv.active_quiz_session_id,
        "blocks": blocks,
        "opening": opening,
    }


@router.post("/interact")
async def interact_endpoint(payload: InteractRequest):
    """发送输入 → SSE 课堂流（块事件）。

    v2：按当前解析的 course_id 查找 Conversation。
    """
    db = SessionLocal()
    try:
        course_id, _ = _resolve_active_course_id(db)
        conv = _get_or_create_conversation(db, course_id)
        _auto_bind_session(db, conv, course_id)

        db.add(Message(conversation_id=conv.id, role="user", type="legacy", content=payload.content))
        db.commit()

        # 作答模式：显式设置当前活跃题目ID，确保判卷反馈精准关联
        if payload.question_id is not None:
            conv.active_quiz_id = payload.question_id
            db.commit()

        async def generate():
            try:
                async for block in interact(db, conv, payload.content):
                    if block.get("kind") != "quiz":
                        db.add(
                            Message(
                                conversation_id=conv.id,
                                role="assistant",
                                type=block.get("kind", "text"),
                                content=(
                                    block.get("content")
                                    or block.get("feedback")
                                    or block.get("message")
                                    or json.dumps(block, ensure_ascii=False)
                                )[:4000],
                            )
                        )
                        db.commit()
                    yield f"data: {json.dumps({'type': 'block', 'block': block}, ensure_ascii=False)}\n\n"
                yield "data: {\"type\": \"done\"}\n\n"
            except AiGatewayError as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield (
                    f"data: {json.dumps({'type': 'error', 'message': f'服务异常：{e}'}, ensure_ascii=False)}\n\n"
                )
            finally:
                db.close()

        return StreamingResponse(generate(), media_type="text/event-stream")
    finally:
        pass


# ---------- 历史保留设置 ----------


@router.get("/retention")
def get_retention(db: Session = Depends(get_db)):
    """获取课堂历史保留天数配置。"""
    return {"days": _get_retention_days(db), "default": DEFAULT_RETENTION_DAYS}


@router.put("/retention")
def set_retention(payload: RetentionRequest, db: Session = Depends(get_db)):
    """设置课堂历史保留天数（1-365）。"""
    _set_setting(db, "classroom_retention_days", str(payload.days))
    return {"days": payload.days}


@router.post("/cleanup")
def cleanup_history(db: Session = Depends(get_db)):
    """手动触发所有课堂对话的历史清理（按当前保留天数）。

    返回每个 conversation 的清理统计。
    """
    retention = _get_retention_days(db)
    convs = list(db.scalars(
        select(Conversation).where(Conversation.mode == "classroom")
    ))
    results = []
    total_deleted = 0
    for conv in convs:
        deleted = _cleanup_old_messages(db, conv.id, retention)
        total_deleted += deleted
        course_name = None
        if conv.course_id:
            c = db.get(Course, conv.course_id)
            course_name = c.name if c else None
        results.append({
            "conversation_id": conv.id,
            "course_id": conv.course_id,
            "course_name": course_name,
            "deleted": deleted,
        })
    return {"retention_days": retention, "total_deleted": total_deleted, "details": results}


# ---------- 挖空背诵 ----------


class ClozeGenerateRequest(BaseModel):
    node_id: int | None = Field(default=None, description="知识点ID（不传则自动选择）")
    blank_count: int = Field(default=3, ge=1, le=10, description="每道题的空格数量")
    question_count: int = Field(default=0, ge=0, le=10, description="生成题目数量，0=AI根据内容自主决定")


class ClozeGradeRequest(BaseModel):
    cloze: dict = Field(description="挖空题数据")
    user_answers: list[str] = Field(description="用户答案列表")
    task_id: int | None = Field(default=None, description="关联任务ID（可选）")


@router.post("/cloze/generate")
async def generate_cloze_endpoint(payload: ClozeGenerateRequest):
    """AI生成挖空背诵题（单次AI调用批量生成，失败降级串行）。"""
    from ..services.cloze_service import generate_cloze, generate_cloze_batch, select_node_for_cloze
    from ..models import KnowledgeNode

    db = SessionLocal()
    try:
        course_id, _ = _resolve_active_course_id(db)
        conv = _get_or_create_conversation(db, course_id)

        ai_decides = payload.question_count <= 0
        question_count = 0 if ai_decides else max(1, min(payload.question_count, 10))
        clozes = []
        selected_nodes = []

        # ---- 第一步：选定知识点 ----
        if payload.node_id is not None:
            node = db.get(KnowledgeNode, payload.node_id)
            if not node:
                raise HTTPException(status_code=404, detail="知识点不存在")
            target_nodes = [node]
            questions_per_node = 0 if ai_decides else question_count
        else:
            # 自动选择：尽量选不重复的知识点（AI决定时选最多3个薄弱节点作为素材）
            max_nodes = 3 if ai_decides else question_count
            used_node_ids = set()
            target_nodes = []
            for _ in range(max_nodes):
                node = select_node_for_cloze(db, conv)
                if not node:
                    break
                attempts = 0
                while node.id in used_node_ids and attempts < 5:
                    node = select_node_for_cloze(db, conv)
                    attempts += 1
                if node.id not in used_node_ids:
                    used_node_ids.add(node.id)
                    target_nodes.append(node)
            if not target_nodes:
                raise HTTPException(status_code=404, detail="未找到合适的知识点")
            # 节点不足时，每个节点多生成几道凑数；AI决定时传0
            if ai_decides:
                questions_per_node = 0
            else:
                questions_per_node = max(1, (question_count + len(target_nodes) - 1) // len(target_nodes))

        # ---- 第二步：优先批量生成（一次AI调用）----
        batch_ok = False
        ai_info = {}
        try:
            batch_results = await generate_cloze_batch(
                db, target_nodes,
                blank_count=payload.blank_count,
                questions_per_node=questions_per_node,
                info_collector=ai_info,
            )
            if batch_results:
                # AI决定数量时不截断；指定数量时截断到请求数
                clozes = batch_results if ai_decides else batch_results[:question_count]
                selected_nodes = [
                    {"id": c.get("node_id"), "name": c.get("node_name")}
                    for c in clozes
                ]
                batch_ok = True
                logger.info("挖空题批量生成成功: %d道（%s）", len(clozes), "AI自主决定" if ai_decides else f"请求{question_count}道")
        except Exception as e:
            logger.warning("批量挖空题生成失败，降级串行: %s", e)

        # ---- 第三步：批量失败或数量不足时，串行补全 ----
        if not batch_ok or (not ai_decides and len(clozes) < question_count):
            needed = 1 if ai_decides else (question_count - len(clozes))
            logger.info("串行补全挖空题: 还需%d道", needed)
            for i in range(needed):
                node = target_nodes[i % len(target_nodes)]
                try:
                    cloze = await generate_cloze(db, conv, node, blank_count=payload.blank_count)
                    cloze["question_index"] = len(clozes) + 1
                    clozes.append(cloze)
                    selected_nodes.append({"id": node.id, "name": node.name})
                except Exception as e:
                    logger.error("串行挖空题生成失败（第%d道）: %s", i + 1, e)
                    break

        if not clozes:
            raise HTTPException(status_code=500, detail="挖空题生成失败：AI服务未返回有效题目")

        # 保存到历史消息（含AI用量信息）
        try:
            msg = Message(
                conversation_id=conv.id,
                role="assistant",
                type="cloze_batch",
                content=json.dumps({
                    "clozes": clozes,
                    "selected_nodes": selected_nodes,
                    "task_id": None,
                }, ensure_ascii=False),
                ai_model=ai_info.get("model"),
                ai_channel=ai_info.get("channel_name"),
                ai_prompt_tokens=ai_info.get("prompt_tokens"),
                ai_completion_tokens=ai_info.get("completion_tokens"),
                ai_total_tokens=ai_info.get("total_tokens"),
                ai_cost=ai_info.get("cost_estimate"),
                ai_duration_ms=ai_info.get("duration_ms"),
            )
            db.add(msg)
            db.commit()
        except Exception as e:
            logger.warning("保存挖空题历史失败: %s", e)
            db.rollback()

        return {
            "success": True,
            "cloze": clozes[0],
            "clozes": clozes,
            "selected_node": selected_nodes[0] if selected_nodes else None,
            "selected_nodes": selected_nodes,
            "question_count": len(clozes),
            "batch_mode": batch_ok,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("挖空题生成失败")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/cloze/grade")
async def grade_cloze_endpoint(payload: ClozeGradeRequest):
    """AI评分挖空背诵题。"""
    from ..services.cloze_service import grade_cloze
    from ..models import Task

    db = SessionLocal()
    try:
        task = None
        if payload.task_id:
            task = db.get(Task, payload.task_id)

        result = await grade_cloze(db, payload.cloze, payload.user_answers, task=task)
        return {"success": True, "result": result}
    except Exception as e:
        logger.exception("挖空题评分失败")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()



class ClozeGradeBatchItem(BaseModel):
    cloze: dict = Field(description="挖空题数据")
    user_answers: list[str] = Field(description="用户答案列表")


class ClozeGradeBatchRequest(BaseModel):
    items: list[ClozeGradeBatchItem] = Field(description="待评分的题目列表")
    task_id: int | None = Field(default=None, description="关联任务ID（可选）")


@router.post("/cloze/grade/batch")
async def grade_cloze_batch_endpoint(payload: ClozeGradeBatchRequest):
    """批量评分挖空题（一次AI调用评分多道题）。"""
    from ..services.cloze_service import grade_cloze_batch
    from ..models import Task

    db = SessionLocal()
    try:
        course_id, _ = _resolve_active_course_id(db)
        conv = _get_or_create_conversation(db, course_id)

        task = None
        if payload.task_id:
            task = db.get(Task, payload.task_id)

        items = [{"cloze": it.cloze, "user_answers": it.user_answers} for it in payload.items]
        ai_info = {}
        result = await grade_cloze_batch(db, items, task=task, info_collector=ai_info)

        # 保存评分结果到历史消息（含AI用量信息）
        try:
            msg = Message(
                conversation_id=conv.id,
                role="assistant",
                type="cloze_feedback",
                content=json.dumps(result, ensure_ascii=False),
                ai_model=ai_info.get("model"),
                ai_channel=ai_info.get("channel_name"),
                ai_prompt_tokens=ai_info.get("prompt_tokens"),
                ai_completion_tokens=ai_info.get("completion_tokens"),
                ai_total_tokens=ai_info.get("total_tokens"),
                ai_cost=ai_info.get("cost_estimate"),
                ai_duration_ms=ai_info.get("duration_ms"),
            )
            db.add(msg)
            db.commit()
        except Exception as e:
            logger.warning("保存挖空题评分历史失败: %s", e)
            db.rollback()

        return {"success": True, "result": result}
    except Exception as e:
        logger.exception("批量挖空题评分失败")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()



class DetailedExplanationRequest(BaseModel):
    question: str = Field(description="题目内容")
    standard_answer: str = Field(default="", description="标准答案")
    user_answer: str = Field(default="", description="用户答案")
    existing_explanation: str = Field(default="", description="现有解析（可选）")
    qtype: str = Field(default="", description="题型：single_choice/fill_cloze/short/code/cloze等")
    grade_detail: str = Field(default="", description="评分详情/反馈（可选）")


@router.post("/detailed-explanation")
async def generate_detailed_explanation(payload: DetailedExplanationRequest):
    """将题目和现有解析发送给AI，生成更详细的解题过程和知识点解析。"""
    from ..services.ai_gateway import chat_stream, AiGatewayError

    qtype_label = {
        "single_choice": "单选题",
        "multiple_choice": "多选题",
        "judge": "判断题",
        "fill_cloze": "多空填空题",
        "fill_single": "填空题",
        "short": "简答题",
        "code": "代码题",
        "cloze": "挖空背诵题",
        "recite": "背诵题",
    }.get(payload.qtype, payload.qtype or "题目")

    system_prompt = f"""你是一个耐心细致的学科辅导老师。请根据下面的题目信息，生成一份**详细的解题过程和知识点解析**。

要求：
1. 先给出完整的解题步骤，一步步推导，不要跳步
2. 解释题目涉及的核心知识点、概念、公式或原理
3. 分析解题思路：为什么这样做，关键突破口是什么
4. 如果用户答案有误，指出错误原因并给出正确思路
5. 总结这类题的通用解题方法和易错点
6. 语言通俗易懂，适合学生理解，不要太学术化
7. 用Markdown格式，分点清晰，重点内容可以加粗

题目类型：{qtype_label}

题目：
{payload.question}

标准答案：{payload.standard_answer or '（无）'}

用户答案：{payload.user_answer or '（未作答）'}

现有解析：{payload.existing_explanation or '（无）'}

评分反馈：{payload.grade_detail or '（无）'}

请生成详细解析："""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请生成详细解题过程和知识点解析"},
    ]

    parts = []
    set_function_type("quiz_answer")
    try:
        async for text in chat_stream(messages):
            parts.append(text)
    except AiGatewayError as e:
        logger.error("详细解析生成失败: %s", e)
        raise HTTPException(status_code=500, detail=f"详细解析生成失败: {e}")

    detailed = "".join(parts).strip()
    if not detailed:
        raise HTTPException(status_code=500, detail="AI未返回详细解析内容")

    return {"success": True, "detailed_explanation": detailed}


# ---------- 管理台：历史信息映射与快捷管理 ----------


@router.get("/admin/conversations")
def admin_list_conversations(db: Session = Depends(get_db)):
    """列出所有课堂对话（含科目名、消息数、最后消息时间），用于管理台快捷定位。"""
    convs = list(db.scalars(
        select(Conversation).where(Conversation.mode == "classroom").order_by(Conversation.id.desc())
    ))
    results = []
    for conv in convs:
        count = db.scalar(
            select(func.count(Message.id)).where(Message.conversation_id == conv.id)
        ) or 0
        last_msg = db.scalar(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.desc()).limit(1)
        )
        course_name = None
        if conv.course_id:
            c = db.get(Course, conv.course_id)
            course_name = c.name if c else None
        results.append({
            "conversation_id": conv.id,
            "course_id": conv.course_id,
            "course_name": course_name,
            "session_id": conv.session_id,
            "message_count": count,
            "last_message_at": last_msg.created_at.isoformat() if last_msg else None,
            "last_message_preview": (last_msg.content[:80] if last_msg and last_msg.content else None),
            "started_at": conv.started_at.isoformat() if conv.started_at else None,
        })
    return results


@router.get("/admin/conversations/{conv_id}/messages")
def admin_list_messages(conv_id: int, db: Session = Depends(get_db)):
    """查看指定对话的消息列表，附带知识点映射（ref_knowledge_ids -> 节点名）。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msgs = list(db.scalars(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)
    ))

    node_ids = set()
    for m in msgs:
        if m.ref_knowledge_ids:
            try:
                ids = json.loads(m.ref_knowledge_ids)
                if isinstance(ids, list):
                    node_ids.update(int(x) for x in ids if str(x).isdigit())
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
    node_map = {}
    if node_ids:
        nodes = list(db.scalars(select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))))
        node_map = {n.id: {"id": n.id, "name": n.name, "subject_id": n.subject_id} for n in nodes}

    results = []
    for m in msgs:
        knowledge_refs = []
        if m.ref_knowledge_ids:
            try:
                ids = json.loads(m.ref_knowledge_ids)
                if isinstance(ids, list):
                    for nid in ids:
                        try:
                            nid_int = int(nid)
                            if nid_int in node_map:
                                knowledge_refs.append(node_map[nid_int])
                            else:
                                knowledge_refs.append({"id": nid_int, "name": f"知识点#{nid_int}(已删除)", "subject_id": None})
                        except (TypeError, ValueError):
                            pass
            except (json.JSONDecodeError, TypeError):
                pass

        content_preview = m.content
        question_preview = None
        if m.type == "quiz":
            try:
                payload = json.loads(m.content)
                question_preview = payload.get("question", "")[:120]
                content_preview = f"[题目] {question_preview}"
            except (json.JSONDecodeError, TypeError):
                pass
        elif m.type == "feedback":
            try:
                payload = json.loads(m.content)
                content_preview = f"[判卷] {payload.get('feedback', payload.get('comment', ''))[:120]}"
            except (json.JSONDecodeError, TypeError):
                pass

        results.append({
            "id": m.id,
            "conversation_id": m.conversation_id,
            "role": m.role,
            "type": m.type,
            "content": m.content,
            "content_preview": (content_preview or "")[:200],
            "question_preview": question_preview,
            "knowledge_refs": knowledge_refs,
            "ai_model": m.ai_model,
            "ai_channel": m.ai_channel,
            "ai_total_tokens": m.ai_total_tokens,
            "ai_cost": m.ai_cost,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    course = db.get(Course, conv.course_id) if conv.course_id else None
    return {
        "conversation_id": conv.id,
        "course_id": conv.course_id,
        "course_name": course.name if course else None,
        "total": len(results),
        "messages": results,
    }


@router.delete("/admin/messages/{msg_id}")
def admin_delete_message(msg_id: int, db: Session = Depends(get_db)):
    """删除单条消息（快捷管理）。"""
    msg = db.get(Message, msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    db.delete(msg)
    db.commit()
    return {"ok": True, "deleted_id": msg_id}


@router.delete("/admin/conversations/{conv_id}/messages")
def admin_clear_conversation(conv_id: int, db: Session = Depends(get_db)):
    """清空指定对话的所有历史消息（保留对话本身），同时重置活跃测验指针。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    result = db.execute(delete(Message).where(Message.conversation_id == conv_id))
    # 重置活跃测验指针，避免旧测验继续出现在课堂状态里
    conv.active_quiz_id = None
    conv.active_quiz_session_id = None
    conv.mainline_json = None
    db.commit()
    return {"ok": True, "conversation_id": conv_id, "deleted": result.rowcount or 0}
