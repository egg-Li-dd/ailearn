"""课堂推理引擎（教练 skill）。

C1：意图判别 + 块生成
C2：主线栈（挂起/恢复）+ 打断恢复
C4：小测批（薄弱节点连环题 + 汇总）

职责边界：记忆/状态全在本 DB 会话内；前端仅渲染。
"""
import json
import logging
from typing import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Conversation, Course, KnowledgeNode, Message, QuizQuestion, StudySession, Task
from ..models.enums import TaskStatus
from .ai_gateway import AiGatewayError, chat_once, chat_stream
from .course_memory import build_opening, format_opening_text, restore_mainline
from .quiz import generate_question, grade_answer, load_payload
from .quiz_contract import OBJECTIVE_TYPES
from .quiz_session import create_session as create_quiz_session, session_to_client_response

logger = logging.getLogger("ailearn.classroom")

MAX_HISTORY_BLOCKS = 12
INTERRUPT_KEYWORDS = ("为什么", "什么是", "解释", "区别", "原理", "怎么", "如何", "讲解", "不懂", "例子", "?")
QUIZ_REQUEST_KEYWORDS = ("来一题", "来一道", "出一道题", "一道题")
# 背诵题关键词：用户要求背诵/记忆某个知识点
RECITE_KEYWORDS = ("背诵", "背一下", "背给我听", "帮我背", "记一下", "记背", "背熟", "背下来", "默写", "记熟", "背记", "要背", "背这个", "背这段")
# 批量/多题出题：全部走多题同屏统一提交模式
BATCH_KEYWORDS = ("小测", "测试一下", "测测", "检测", "考核", "做题", "出题", "练习", "出几道题", "出几题", "再来几题", "再出几题", "再出几道题", "几道题", "几题", "再来一组", "再出一组")
# 课间互动：多题同屏统一提交模式（区别于逐题流水式小测）
CLASS_BREAK_KEYWORDS = ("课间", "课间小测", "课间互动", "来一组", "多题", "一组题", "统一做", "出一组题", "新题", "再来一组", "重新出题", "再来一组题")

BATCH_SIZE = 5
TASK_PASS_SCORE = 80  # 任务通过阈值（百分制）：客观题需满分、主观题需≥80（良好线），统一用80作为达标线


# ---------- 上下文辅助 ----------


def _mainline(conv: Conversation) -> dict:
    try:
        return json.loads(conv.mainline_json) if conv.mainline_json else {}
    except json.JSONDecodeError:
        return {}


def _save_mainline(db: Session, conv: Conversation, data: dict) -> None:
    conv.mainline_json = json.dumps(data, ensure_ascii=False)
    db.commit()


def _history_blocks(db: Session, conv: Conversation) -> list[dict]:
    msgs = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(MAX_HISTORY_BLOCKS)
        )
    )
    out = []
    for m in reversed(msgs):
        if m.type == "quiz":
            try:
                payload = json.loads(m.content)
                out.append({"role": "assistant", "kind": "quiz", "text": payload.get("question", "")})
                continue
            except json.JSONDecodeError:
                pass
        out.append({"role": m.role, "kind": m.type if m.type != "legacy" else "text", "text": m.content})
    return out


def _coach_system_prompt(conv: Conversation, context: dict) -> str:
    """课堂教练 system（精简版）。

    优化：知识点讲解/总结的详细要求不再常驻 system（约350字/次），
    改为在 _gen_text_blocks 中检测到讲解/总结意图时按需注入 user 消息。
    预计日常对话 system token 降低 40-50%。
    """
    parts = [
        "你是 ai学 的学习教练（课堂模式）。你讲话认真、直接、有判断力。",
        "回答中涉及知识点时用 [[知识点名]] 标注（最多 5 个，名称要精确）。",
    ]
    if context.get("course_name"):
        parts.append(f"当前课程：{context['course_name']}。")
    if context.get("knowledge"):
        parts.append(
            f"当前知识点「{context['knowledge']['name']}」（掌握度 {context['knowledge']['mastery']}）。"
        )
    return "".join(parts)



def _detail_requirements() -> str:
    """知识点讲解/总结的详细要求（按需注入，不常驻 system）。"""
    return (
        "\n\n【知识点讲解要求】当用户要求讲解、总结、梳理知识点时，必须详细展开，"
        "每个知识点至少包含：①准确定义（用自己的话讲清本质）②核心要点（分点列出关键概念/公式/性质）"
        "③典型例子或应用（帮助理解）④常见误区或易错点。禁止只给一句话概括，禁止用关键词堆砌代替解释。"
        "【总结知识点要求】当用户说'总结知识点'/'梳理一下'/'归纳重点'时，必须自动读取当前学习会话的"
        "学习中/待完成任务列表（正在学的小节+下一节课/没学的小节），优先总结这些任务涉及的知识点（学习中的优先）。"
        "先列出当前涉及的核心知识点清单，然后对每个知识点逐一详细讲解（按上面的知识点讲解要求），"
        "最后给出学习建议和复习优先级。如果没有学习中/待完成任务，再总结当前课程的薄弱知识点。"
        "不要让用户手动指定范围，直接基于任务列表自动总结。"
    )

def _course_context(db: Session, conv: Conversation) -> dict:
    context: dict = {"course_name": None, "course_id": None, "knowledge": None}
    # v2：直接用 conversation 自身绑定的 session_id，不再用 in_class 硬覆盖
    # （自动绑定逻辑已在 router 层的 _auto_bind_session 处理）
    session_id = conv.session_id
    if session_id is not None:
        ss = db.get(StudySession, session_id)
        if ss:
            course = db.get(Course, ss.course_id)
            context["course_id"] = ss.course_id
            context["course_name"] = course.name if course else None
    # 如果 conversation 没有 session_id 但有 course_id（手动切换到无课科目），用 course_id 补全
    if context["course_id"] is None and conv.course_id is not None:
        course = db.get(Course, conv.course_id)
        context["course_id"] = conv.course_id
        context["course_name"] = course.name if course else None
    ml = _mainline(conv)
    kid = ml.get("active_knowledge")
    if kid:
        node = db.get(KnowledgeNode, kid)
        if node:
            context["knowledge"] = {"id": node.id, "name": node.name, "mastery": node.mastery}
    return context


def _get_current_task(db: Session, conv: Conversation) -> Task | None:
    """获取当前课堂会话中第一个待完成/学习中且关联了知识点的任务。

    课堂-任务联动的核心查询：
    - 仅当 conv.session_id 已绑定学习会话（即"在课堂中"）时有效
    - 按 seq 升序取第一个 status in (todo, doing) 且 target_knowledge_id 非空的任务
    - 无知识点关联的任务（如纯阅读/思考）不参与出题驱动，自动跳过
    """
    if conv.session_id is None:
        return None
    return db.scalar(
        select(Task)
        .where(
            Task.session_id == conv.session_id,
            Task.status.in_([TaskStatus.TODO, TaskStatus.DOING]),
            Task.target_knowledge_id.isnot(None),
        )
        .order_by(Task.seq, Task.id)
        .limit(1)
    )


def _get_pending_tasks(db: Session, conv: Conversation, *, limit: int = 5) -> list[Task]:
    """获取当前课堂会话中多个待完成/学习中且关联了知识点的任务（下一节课/没学的小节）。

    用于批量出题和总结知识点时自动确定范围。
    - 仅当 conv.session_id 已绑定学习会话时有效
    - 按 seq 升序取前 N 个 status in (todo, doing) 且 target_knowledge_id 非空的任务
    - 去重：同一知识点只取第一个任务
    - 优先级：学习中（doing）的任务排在前面，然后是待完成（todo）的任务
    """
    if conv.session_id is None:
        return []
    # 先查学习中的任务，再查待完成的任务，合并后去重
    doing_tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.session_id == conv.session_id,
                Task.status == TaskStatus.DOING,
                Task.target_knowledge_id.isnot(None),
            )
            .order_by(Task.seq, Task.id)
            .limit(limit)
        )
    )
    todo_tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.session_id == conv.session_id,
                Task.status == TaskStatus.TODO,
                Task.target_knowledge_id.isnot(None),
            )
            .order_by(Task.seq, Task.id)
            .limit(limit * 2)
        )
    )
    # 合并：学习中任务在前，待完成任务在后
    all_tasks = doing_tasks + todo_tasks
    # 去重：同一知识点只取第一个任务
    seen_nodes = set()
    result = []
    for task in all_tasks:
        if task.target_knowledge_id not in seen_nodes:
            seen_nodes.add(task.target_knowledge_id)
            result.append(task)
            if len(result) >= limit:
                break
    return result


# ---------- 块生成 ----------


async def _gen_text_blocks(
    db: Session, conv: Conversation, user_input: str, context: dict
) -> AsyncIterator[dict]:
    history = _history_blocks(db, conv)
    messages = [{"role": "system", "content": _coach_system_prompt(conv, context)}]
    # 历史消息转换为标准 OpenAI 格式（text → content），并过滤空内容
    for h in history[-8:]:
        content = h.get("text", "") or ""
        if content.strip():
            messages.append({"role": h["role"], "content": content})

    # 总结/梳理/归纳请求：自动读取待完成/学习中任务列表，注入到用户输入中
    summary_keywords = ["总结", "梳理", "归纳", "复习", "知识点", "重点", "回顾", "整理"]
    if any(kw in user_input for kw in summary_keywords):
        pending_tasks = _get_pending_tasks(db, conv, limit=5)
        if pending_tasks:
            task_info = "\n\n【当前学习中/待完成任务列表（自动读取，优先总结这些知识点）】\n"
            for i, task in enumerate(pending_tasks, 1):
                node = db.get(KnowledgeNode, task.target_knowledge_id) if task.target_knowledge_id else None
                node_name = node.name if node else "未知知识点"
                status_label = "学习中" if task.status == TaskStatus.DOING else "待完成"
                task_info += f"{i}. [{status_label}] 任务「{task.title}」→ 知识点：{node_name}\n"
            task_info += "请优先总结以上任务涉及的知识点（学习中的优先）。"
            user_input = user_input + task_info
            # 按需注入知识点讲解/总结详细要求（精简 system 后移到这里）
            user_input += _detail_requirements()
            logger.info("总结请求自动注入任务列表: %d 个学习中/待完成任务", len(pending_tasks))

    # 讲解/提问请求：通用检测，按需注入详细要求（精简 system 后移到这里）
    detail_keywords = ["讲解", "讲一下", "解释", "什么是", "为什么", "怎么理解", "原理", "概念", "公式", "推导"]
    if any(kw in user_input for kw in detail_keywords) and "_detail_requirements()" not in user_input:
        user_input = user_input + _detail_requirements()

    messages.append({"role": "user", "content": user_input})
    parts: list[str] = []
    info_collector: dict = {}
    try:
        set_function_type("classroom")
        async for text in chat_stream(messages, info_collector=info_collector):
            parts.append(text)
    except AiGatewayError as e:
        yield {"kind": "error", "message": str(e)}
        return
    content = "".join(parts)
    # 保存AI回复到数据库，并记录token、模型、费用信息
    try:
        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            type="text",
            content=content,
            ai_model=info_collector.get("model"),
            ai_channel=info_collector.get("channel_name"),
            ai_prompt_tokens=info_collector.get("prompt_tokens"),
            ai_completion_tokens=info_collector.get("completion_tokens"),
            ai_total_tokens=info_collector.get("total_tokens"),
            ai_cost=info_collector.get("cost_estimate"),
            ai_duration_ms=info_collector.get("duration_ms"),
        )
        db.add(msg)
        db.commit()
    except Exception as e:
        logger.error("保存AI回复失败: %s", e, exc_info=True)
        db.rollback()
    # 瘦身 ai_info：只保留前端渲染需要的 3 个字段（其余已存数据库 Message 表）
    _ai_info_slim = None
    if info_collector:
        _ai_info_slim = {
            "model": info_collector.get("model"),
            "total_tokens": info_collector.get("total_tokens"),
            "cost_estimate": info_collector.get("cost_estimate"),
        }
    yield {
        "kind": "text",
        "content": content,
        "ai_info": _ai_info_slim,
    }


def _detect_intent_keyword(user_input: str, conv: Conversation) -> str:
    """基于关键词的意图识别（fallback）。"""
    ml = _mainline(conv)
    # 背诵请求优先：用户说"背诵XXX"时生成背诵题
    if any(kw in user_input for kw in RECITE_KEYWORDS):
        return "recite_request"
    # 出题请求优先检查：即使有活跃 session，用户说"新题/再出几道题"也应开始新题
    if any(kw in user_input for kw in CLASS_BREAK_KEYWORDS) or any(kw in user_input for kw in BATCH_KEYWORDS):
        return "class_break_request"
    # 批量/课间互动模式：有活跃 session
    if conv.active_quiz_session_id is not None:
        # 总结/讲解/梳理知识点：即使有活跃 session，也应正常处理为 explain
        summary_keywords = ["总结", "梳理", "归纳", "讲解", "复习", "知识点", "重点", "回顾", "整理", "讲一下", "解释"]
        if any(kw in user_input for kw in summary_keywords):
            return "explain"
        if any(kw in user_input for kw in INTERRUPT_KEYWORDS) and len(user_input) < 40:
            return "interrupt"
        return "session_answer"
    # 单题模式
    if conv.active_quiz_id is not None:
        if any(kw in user_input for kw in INTERRUPT_KEYWORDS) and len(user_input) < 40:
            return "interrupt"
        return "answer"
    if any(kw in user_input for kw in QUIZ_REQUEST_KEYWORDS):
        return "quiz_request"
    return "explain"


async def _detect_intent_ai(db: Session, user_input: str, conv: Conversation) -> str:
    """基于 AI 语义理解的意图识别。

    让 AI 根据用户输入和当前对话状态判断意图，比关键词匹配更灵活。
    AI 调用失败时回退到关键词匹配。
    可通过 ai.intent_model 配置独立指定意图识别用的模型（如更便宜的模型），
    未配置时使用渠道默认模型。
    """
    has_active_session = conv.active_quiz_session_id is not None
    has_active_quiz = conv.active_quiz_id is not None

    prompt = f"""你是一个学习助手的意图分类器。根据用户输入和当前对话状态，判断用户的意图。

【当前状态】
- 是否有活跃的多题小测（session）：{has_active_session}
- 是否有活跃的单题：{has_active_quiz}

【用户输入】
{user_input}

【意图分类】请从以下选项中选择一个最匹配的：
- recite_request：用户要求背诵/记忆某个知识点（如"背诵牛顿第二定律"、"背一下这个"、"记一下二分查找"、"帮我背"、"默写"、"背给我听"）
- class_break_request：用户要求出多道题/小测/课间互动（如"出几道题"、"小测"、"新题"、"考考我"、"再来点题"、"给我整几道"、"测试一下"）
- quiz_request：用户要求出一道题（如"来一题"、"出一道题"、"练一题"）
- session_answer：用户在多题小测进行中输入普通文本（非出题、非提问），应提示通过界面作答
- answer：用户在单题模式中输入答案
- interrupt：用户在答题过程中提问（如"为什么"、"什么是"、"解释一下"、"这个知识点不懂"）
- explain：普通讲解/问答/总结（用户问问题、要求解释概念、总结知识点、梳理重点、归纳内容等）

【输出要求】
只输出意图名称（如 class_break_request），不要任何其他文字、解释或标点。"""

    # 读取意图识别功能配置：优先功能配置(ai.func.intent_classify.*)，回退通用配置(ai.intent_model)
    from ..models import UserSetting
    func_model = None
    func_temp = 0.1
    rows = db.execute(
        select(UserSetting.key, UserSetting.value).where(
            UserSetting.key.in_(["ai.func.intent_classify.model", "ai.func.intent_classify.temperature"])
        )
    ).all()
    for k, v in rows:
        if k.endswith(".model") and v:
            func_model = v
        elif k.endswith(".temperature") and v:
            try:
                func_temp = float(v)
            except (TypeError, ValueError):
                pass
    if not func_model:
        from ..core.ai_config import read_ai_config
        func_model = read_ai_config(db).get("intent_model") or None

    # 标记功能类型，供调用日志分类
    from ..services.call_logger import reset_function_type, set_function_type
    ft_token = set_function_type("intent_classify")

    try:
        result = await chat_once(
            [{"role": "user", "content": prompt}],
            temperature=func_temp,
            model=func_model,
            db=db,
        )
        intent = result.strip().lower().strip('"\'`.,;:')
        valid_intents = {
            "recite_request", "class_break_request", "quiz_request", "session_answer",
            "answer", "interrupt", "explain",
        }
        if intent in valid_intents:
            logger.info("AI意图识别: %s (输入: %s)", intent, user_input[:30])
            return intent
        logger.warning("AI返回未知意图 '%s'，回退关键词匹配", intent)
    except (AiGatewayError, Exception) as e:
        logger.warning("AI意图识别失败: %s，回退关键词匹配", e)
    finally:
        reset_function_type(ft_token)

    return _detect_intent_keyword(user_input, conv)


def _pick_quiz_targets(db: Session, conv: Conversation, context: dict, limit: int = 5, *, force_multi: bool = False) -> list[KnowledgeNode]:
    """选题：课堂任务驱动 > 当前知识点 > 课程内掌握度最低的叶子。

    Args:
        force_multi: 强制多节点模式（批量出题时用）。为 True 时跳过单节点
                     优先逻辑（任务驱动/当前知识点），直接从课程薄弱节点选多个，
                     避免"出几道题"却只出1题的问题。

    优先级说明：
    0. 课堂任务驱动：当 conv.session_id 绑定了学习会话且存在待完成任务时，
       用任务的 target_knowledge_id 出题——这是课堂-任务联动的入口。
       批量出题时优先取多个待完成任务的知识点（下一节课/没学的小节）。
    1. 当前活跃知识点（mainline.active_knowledge）：用户正在学的节点。
    2. 课程内薄弱节点：level>=3 按 mastery 升序取前 N 个。
    """
    # 优先级0：课堂任务驱动（单题和批量都优先考虑任务）
    tasks = _get_pending_tasks(db, conv, limit=limit)
    if tasks:
        task_nodes = []
        for task in tasks:
            if task.target_knowledge_id:
                node = db.get(KnowledgeNode, task.target_knowledge_id)
                if node and node not in task_nodes:
                    task_nodes.append(node)
        if task_nodes:
            if not force_multi:
                # 单题：返回第一个任务节点
                return [task_nodes[0]]
            # 批量：返回任务节点，不足时用薄弱节点补充
            if len(task_nodes) >= limit:
                return task_nodes[:limit]
            # 任务节点不足，用薄弱节点补充
            course_id = context.get("course_id")
            if course_id:
                weak_nodes = list(
                    db.scalars(
                        select(KnowledgeNode)
                        .where(KnowledgeNode.subject_id == course_id, KnowledgeNode.level >= 3)
                        .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
                        .limit(limit - len(task_nodes))
                    )
                )
                for n in weak_nodes:
                    if n not in task_nodes:
                        task_nodes.append(n)
            return task_nodes[:limit]

    if not force_multi:
        # 优先级1：当前活跃知识点
        if context.get("knowledge"):
            n = db.get(KnowledgeNode, context["knowledge"]["id"])
            if n:
                return [n]
    # 优先级2：课程内掌握度最低的叶子
    course_id = context.get("course_id")
    if course_id:
        nodes = list(
            db.scalars(
                select(KnowledgeNode)
                .where(KnowledgeNode.subject_id == course_id, KnowledgeNode.level >= 3)
                .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
                .limit(limit)
            )
        )
        if nodes:
            return nodes
    return []


async def _emit_quiz(
    db: Session, conv: Conversation, node: KnowledgeNode, *, batch: dict | None = None,
    force_type: str | None = None,
) -> dict:
    """生成一题并落库，返回 quiz 块。

    Args:
        force_type: 强制题型（如 'recite' 背诵题），None 则按掌握度自动选。
    """
    q = await generate_question(db, node.id, force_type=force_type)
    conv.active_quiz_id = q.id
    ml = _mainline(conv)
    ml["active_knowledge"] = node.id
    ml["last_quiz"] = q.id
    # 任务联动：如果出题节点匹配当前未完成任务，记录 active_task_id
    # 判分达标后据此标记任务完成
    current_task = _get_current_task(db, conv)
    if current_task and current_task.target_knowledge_id == node.id:
        ml["active_task_id"] = current_task.id
    else:
        ml.pop("active_task_id", None)
    if batch is not None:
        ml["batch"] = batch
    _save_mainline(db, conv, ml)
    payload = load_payload(q)
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            type="quiz",
            content=json.dumps(
                {**payload, "_node_id": node.id, "_quiz_id": q.id, "qtype": q.qtype, "question_type": q.qtype},
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    block = {
        "kind": "quiz",
        "id": q.id,
        "qtype": q.qtype,
        "difficulty": q.difficulty,
        "question": payload.get("question", ""),
        "options": payload.get("options", []),
        "node": {"id": node.id, "name": node.name, "mastery": node.mastery},
    }
    # 主观题（简答/代码）附带参考答案与满分，供前端「手写作答」批改用
    if q.qtype in ("short", "code"):
        block["reference_answer"] = payload.get("correct_answer", "")
        block["points"] = payload.get("points", 3)
    # 多空填空附带脱敏 blanks（id+hint），供前端逐空渲染
    if q.qtype == "fill_cloze":
        block["blanks"] = [
            {"id": b.get("id"), "hint": b.get("hint")}
            for b in (payload.get("blanks") or [])
            if isinstance(b, dict)
        ]
    # 背诵题：返回全文、分段、阶梯步数、理解辅助（背诵需要看原文，隐藏是前端交互）
    if q.qtype == "recite":
        block["content"] = payload.get("content", "")
        block["segments"] = payload.get("segments", [])
        block["ladder_steps"] = payload.get("ladder_steps", 4)
        block["explanation"] = payload.get("explanation", "")
    if batch is not None:
        block["batch_progress"] = f"{batch['current'] + 1}/{batch['total']}"
    return block


# ---------- 闭合检查 ----------

CLOSING_MAX_ATTEMPTS = 2


async def _handle_closing_check(
    db: Session, conv: Conversation, user_input: str, context: dict
) -> AsyncIterator[dict]:
    """闭合检查：评估学习者用自己的话复述知识点的质量。

    对应 OpenMAIC PBL v2 的 record_closing_check 工具：
    - weak：理解有偏差 → 自动补充讲解 + 再试一次（最多CLOSING_MAX_ATTEMPTS次）
    - ok / strong：理解到位 → 记录 concept_unlocked，清除闭合状态
    """
    ml = _mainline(conv)
    closing = ml.get("closing_check") or {}
    node_id = closing.get("node_id")
    node_name = closing.get("node_name") or "这个知识点"
    attempt = closing.get("attempt", 0)

    quality_prompt = f"""你是学习教练。学习者刚做完一道关于「{node_name}」的题，现在用自己的话复述对这个知识点的理解。
请评估理解质量，只输出一个词：weak、ok 或 strong。

评估标准：
- weak：理解有明显错误、关键概念遗漏、或完全没说到点子上
- ok：核心意思对了，但不够完整或有小瑕疵
- strong：理解准确完整，能用自己的话讲清楚本质

学习者的回答：
{user_input}

只输出 weak / ok / strong，不要任何其他文字。"""

    try:
        from .call_logger import reset_function_type, set_function_type
        ft_token = set_function_type("closing_check")
        try:
            quality_raw = await chat_once(
                [{"role": "user", "content": quality_prompt}],
                temperature=0.1,
                db=db,
            )
        finally:
            reset_function_type(ft_token)
        quality = quality_raw.strip().lower().strip('"\'`.,;:！。，；：')
        if quality not in ("weak", "ok", "strong"):
            quality = "ok"
    except Exception as e:
        logger.warning("闭合检查质量评估失败: %s，回退为ok", e)
        quality = "ok"

    logger.info("闭合检查: node=%s quality=%s attempt=%d", node_name, quality, attempt)

    if quality == "weak" and attempt < CLOSING_MAX_ATTEMPTS:
        closing["attempt"] = attempt + 1
        ml["closing_check"] = closing
        _save_mainline(db, conv, ml)

        explain_input = (
            f"学习者对「{node_name}」的理解有偏差。请用简洁的方式重新讲解这个知识点的核心，"
            f"指出刚才回答中的问题，给一个具体例子帮助理解。不要太长，3-5句话。"
        )
        async for ev in _gen_text_blocks(db, conv, explain_input, context):
            yield ev

        yield {
            "kind": "text",
            "content": "再试一次：用你自己的话说说这个知识点的核心意思，不用背定义。",
        }
        return

    if node_id:
        unlocked = ml.get("concepts_unlocked", [])
        if node_id not in unlocked:
            unlocked.append(node_id)
        ml["concepts_unlocked"] = unlocked

    ml.pop("closing_check", None)
    _save_mainline(db, conv, ml)

    if quality == "strong":
        yield {
            "kind": "text",
            "content": f"很好！「{node_name}」这块你理解得很到位，已经掌握了。可以说'再来一题'巩固，或者'总结'梳理一下。",
        }
    elif quality == "ok":
        yield {
            "kind": "text",
            "content": f"不错，「{node_name}」的核心意思你get到了。想更扎实可以说'再来一题'，或者继续学新内容。",
        }
    else:
        yield {
            "kind": "text",
            "content": f"「{node_name}」这块还需要多练。建议说'再来一题'做道变式题巩固，或者说'讲解'让我再详细讲一遍。",
        }


def _closing_check_active(conv: Conversation) -> bool:
    ml = _mainline(conv)
    return bool((ml.get("closing_check") or {}).get("active"))


def _clear_closing_check(db: Session, conv: Conversation) -> None:
    ml = _mainline(conv)
    if "closing_check" in ml:
        ml.pop("closing_check", None)
        _save_mainline(db, conv, ml)


# ---------- 主流程 ----------


async def interact(db: Session, conv: Conversation, user_input: str) -> AsyncIterator[dict]:
    context = _course_context(db, conv)

    # 课初开场注入：新对话（尚无 assistant 消息）+ 有课程上下文
    assistant_count = db.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == conv.id, Message.role == "assistant"
        )
    )
    if assistant_count == 0 and context.get("course_id"):
        opening = build_opening(db, context["course_id"])
        restored = restore_mainline(db, conv, opening)
        opening_text = format_opening_text(opening)
        if opening_text:
            yield {"kind": "text", "content": opening_text}
        # 恢复遗留题目：重新输出 quiz 块（新对话无历史消息）
        if restored and opening.get("pending_quiz_id"):
            quiz = db.get(QuizQuestion, opening["pending_quiz_id"])
            if quiz:
                node = db.get(KnowledgeNode, quiz.node_id)
                payload = load_payload(quiz)
                conv.active_quiz_id = quiz.id
                db.commit()
                restored_block = {
                    "kind": "quiz",
                    "id": quiz.id,
                    "qtype": quiz.qtype,
                    "difficulty": quiz.difficulty,
                    "question": payload.get("question", ""),
                    "options": payload.get("options", []),
                    "node": {"id": node.id, "name": node.name, "mastery": node.mastery} if node else None,
                }
                if quiz.qtype in ("short", "code"):
                    restored_block["reference_answer"] = payload.get("correct_answer", "")
                    restored_block["points"] = payload.get("points", 3)
                if quiz.qtype == "fill_cloze":
                    restored_block["blanks"] = [
                        {"id": b.get("id"), "hint": b.get("hint")}
                        for b in (payload.get("blanks") or [])
                        if isinstance(b, dict)
                    ]
                if quiz.qtype == "recite":
                    restored_block["content"] = payload.get("content", "")
                    restored_block["segments"] = payload.get("segments", [])
                    restored_block["ladder_steps"] = payload.get("ladder_steps", 4)
                    restored_block["explanation"] = payload.get("explanation", "")
                yield restored_block
                return  # 恢复题目后等待用户作答，不继续解析输入

    intent = await _detect_intent_ai(db, user_input, conv)
    logger.info("conv %d intent=%s", conv.id, intent)

    # 闭合检查：如果在闭合检查中，且不是明确的指令类意图，走闭合评估
    if _closing_check_active(conv):
        command_intents = {"quiz_request", "class_break_request", "recite_request", "batch_request"}
        is_summary = any(kw in user_input for kw in ["总结", "梳理", "归纳", "复习", "重点", "回顾", "整理"])
        if intent in command_intents or is_summary:
            _clear_closing_check(db, conv)  # 用户主动发指令，清除闭合状态
        elif intent == "interrupt":
            # 闭合检查中的提问：先答疑，再提示回到闭合问题
            # （闭合检查中active_quiz_id已为None，不会走到下方的interrupt流）
            async for ev in _gen_text_blocks(db, conv, user_input, context):
                yield ev
            _closing_node = (_mainline(conv).get("closing_check") or {}).get("node_name", "这个知识点")
            yield {
                "kind": "text",
                "content": f"回到刚才的闭合问题：用你自己的话说说「{_closing_node}」的核心意思。",
            }
            return
        else:
            async for ev in _handle_closing_check(db, conv, user_input, context):
                yield ev
            return

    # 课间互动会话活跃时，用户文本输入 → 提示通过界面作答
    if intent == "session_answer":
        from ..models import QuizSession as QS
        session = db.get(QS, conv.active_quiz_session_id)
        if session and session.status == "awaiting_submit":
            yield {
                "kind": "text",
                "content": (
                    f"当前有课间小测（{session.title or '未命名'}）正在进行中。"
                    "请在下方题目界面直接作答，全部答完后点「提交全部」按钮，我会逐题批改。"
                    "如果需要问问题，直接问我就行，不影响答题。"
                ),
            }
        elif session and session.status == "graded":
            # 小测已批改完成：如果用户要求总结/讲解/梳理知识点，正常处理
            summary_keywords = ["总结", "梳理", "归纳", "讲解", "复习", "知识点", "重点", "回顾", "整理"]
            if any(kw in user_input for kw in summary_keywords):
                logger.info("小测已批改，用户要求总结知识点，正常处理")
                async for ev in _gen_text_blocks(db, conv, user_input, context):
                    yield ev
            else:
                yield {
                    "kind": "text",
                    "content": (
                        "课间小测已批改完成。可以点「一键重做」重新练习，或说「新题」再来一组。"
                        "有问题随时问我，也可以说「总结知识点」来梳理本次涉及的内容。"
                    ),
                }
        else:
            # session 异常，清理状态
            conv.active_quiz_session_id = None
            db.commit()
            async for ev in _gen_text_blocks(db, conv, user_input, context):
                yield ev
        return

    # 判卷流
    if intent == "answer" and conv.active_quiz_id is not None:
        active_quiz = db.get(QuizQuestion, conv.active_quiz_id)
        if active_quiz:
            yield {"kind": "feedback", "text": "判卷中…"}
            try:
                answer = await grade_answer(db, active_quiz.id, user_input)
            except ValueError as e:
                yield {"kind": "error", "message": str(e)}
                return
            conv.active_quiz_id = None
            ml = _mainline(conv)
            batch = ml.get("batch")
            if batch is not None:
                batch.setdefault("results", []).append(
                    {"quiz_id": active_quiz.id, "score": answer.score}
                )
            db.commit()

            node = db.get(KnowledgeNode, active_quiz.node_id)
            fb_payload = load_payload(active_quiz)
            try:
                fb_inner = json.loads(answer.ai_feedback) if answer.ai_feedback else {}
            except (json.JSONDecodeError, TypeError):
                fb_inner = {}
            # correct：客观题（选择/判断/填空）按分数>=100；背诵题用自评结果；主观题（简答/代码）为 None
            if active_quiz.qtype in OBJECTIVE_TYPES:
                correct = answer.score >= 100
            elif active_quiz.qtype == "recite":
                correct = fb_inner.get("correct", False) if isinstance(fb_inner, dict) else False
            else:
                correct = None
            # 标准答案：背诵题用全文 content，其余用 correct_answer
            if active_quiz.qtype == "recite":
                standard_answer = fb_payload.get("content", "")
            else:
                standard_answer = str(fb_payload.get("correct_answer", fb_payload.get("answer", "")))
            # 瘦身：feedback 改为纯文本（原 feedback_text 逻辑），移除 feedback_text 字段
            # 原 answer.ai_feedback 是完整 JSON（含 option_results/blank_results 等内部字段），
            # 前端直接显示会是 JSON 字符串；这里提取纯文本反馈，同时修复前端显示 bug
            _feedback_text = ""
            if isinstance(fb_inner, dict):
                _feedback_text = (
                    fb_inner.get("feedback_text")
                    or fb_inner.get("ai_feedback_text")
                    or fb_inner.get("analysis")
                    or fb_inner.get("feedback")
                    or ""
                )
            yield {
                "kind": "feedback",
                "question_id": active_quiz.id,
                "correct": correct,
                "score": answer.score,
                "user_answer": fb_inner.get("user_answer", user_input) if isinstance(fb_inner, dict) else user_input,
                "feedback": _feedback_text,
                "explanation": fb_payload.get("explanation", ""),
                "standard_answer": standard_answer,
                "recite_rating": fb_inner.get("recite_rating") if isinstance(fb_inner, dict) else None,
                "node": {"id": node.id, "name": node.name, "mastery": node.mastery} if node else None,
            }

            # === 任务联动：判分达标后标记任务完成 ===
            active_task_id = ml.get("active_task_id")
            if active_task_id:
                task = db.get(Task, active_task_id)
                if task and task.status == TaskStatus.TODO:
                    if answer.score >= TASK_PASS_SCORE:
                        task.status = TaskStatus.DONE
                        db.commit()
                        ml.pop("active_task_id", None)
                        _save_mainline(db, conv, ml)
                        next_task = _get_current_task(db, conv)
                        if next_task:
                            yield {
                                "kind": "text",
                                "content": (
                                    f"任务「{task.title}」已完成（得分 {answer.score}）！"
                                    f"下一个任务：{next_task.title}，继续加油。"
                                ),
                            }
                        else:
                            yield {
                                "kind": "text",
                                "content": (
                                    f"任务「{task.title}」已完成（得分 {answer.score}）！"
                                    "本课堂任务全部搞定，很棒！"
                                ),
                            }
                    else:
                        yield {
                            "kind": "text",
                            "content": (
                                f"任务「{task.title}」尚未通过（得分 {answer.score}，需达到 {TASK_PASS_SCORE}），"
                                "再练一次巩固一下。"
                            ),
                        }

            # 小测批：续题或汇总
            if batch is not None:
                results = batch.get("results", [])
                if len(results) >= batch.get("total", BATCH_SIZE):
                    ml.pop("batch", None)
                    _save_mainline(db, conv, ml)
                    from ..models import QuizQuestion as QQ

                    qs = {q.id: q for q in db.scalars(select(QQ).where(QQ.id.in_([r["quiz_id"] for r in results])))}
                    ok_n = sum(1 for r in results if qs.get(r["quiz_id"]) and r["score"] >= (100 if qs[r["quiz_id"]].qtype in OBJECTIVE_TYPES else 60))
                    yield {
                        "kind": "text",
                        "content": (
                            f"小测完成：{ok_n}/{len(results)} 题过关。"
                            "薄弱点已记录，接下来复习队列会安排它们。"
                        ),
                    }
                    return
                # 继续下一题
                targets = _pick_quiz_targets(db, conv, context, limit=BATCH_SIZE)
                if targets:
                    batch["current"] = len(results)
                    _save_mainline(db, conv, ml)
                    node2 = targets[0]
                    try:
                        yield await _emit_quiz(db, conv, node2, batch=batch)
                    except (AiGatewayError, ValueError) as e:
                        yield {"kind": "error", "message": str(e)}
                return

            # 非批：进入闭合检查（替代原弱项自动讲解，闭合检查会更智能地处理）
            if batch is None and conv.active_quiz_session_id is None and node:
                ml_closing = _mainline(conv)
                ml_closing["closing_check"] = {
                    "active": True,
                    "node_id": node.id,
                    "node_name": node.name,
                    "quiz_id": active_quiz.id,
                    "attempt": 0,
                    "score": answer.score,
                }
                _save_mainline(db, conv, ml_closing)
                yield {
                    "kind": "text",
                    "content": (
                        f"题目讲完了。来个闭合小检查：用你自己的话说说"
                        f"「{node.name}」的核心意思，不用背定义，讲明白就行。"
                    ),
                }
            return

    # 打断流：挂起当前题，答疑后恢复（coach_exit）
    if intent == "interrupt" and conv.active_quiz_id is not None:
        ml = _mainline(conv)
        ml["pending_quiz"] = conv.active_quiz_id
        ml.pop("batch", None)  # 批中打断：先退出批
        conv.active_quiz_id = None
        db.commit()
        async for ev in _gen_text_blocks(db, conv, user_input, context):
            yield ev
        pending = ml.get("pending_quiz")
        if pending:
            yield {"kind": "coach_exit", "message": "回到刚才的题目，想好了直接把答案发给我。"}
        ml.pop("pending_quiz", None)
        # 答疑完后，如果在闭合检查中，提示回到闭合问题
        if _closing_check_active(conv):
            closing_node = (ml.get("closing_check") or {}).get("node_name", "这个知识点")
            yield {
                "kind": "text",
                "content": f"回到刚才的闭合问题：用你自己的话说说「{closing_node}」的核心意思。",
            }
        _save_mainline(db, conv, ml)
        return

    # 课间互动：多题同屏统一提交模式
    if intent == "class_break_request":
        # force_multi=True：批量出题时跳过单节点优先逻辑，从课程选多个薄弱知识点
        targets = _pick_quiz_targets(db, conv, context, limit=BATCH_SIZE, force_multi=True)
        if not targets:
            async for ev in _gen_text_blocks(db, conv, user_input, context):
                yield ev
            return
        # 解析题目数量（如"课间小测3题"）
        import re
        m = re.search(r'(\d+)\s*题', user_input)
        count = int(m.group(1)) if m else min(3, len(targets))
        count = max(1, min(count, len(targets)))
        # 课间小测强制题型多样化：填空→单选→判断→多选→填空，循环
        from .quiz_contract import QTYPE_FILL_CLOZE, QTYPE_SINGLE_CHOICE, QTYPE_JUDGE, QTYPE_MULTIPLE_CHOICE
        _type_cycle = [QTYPE_FILL_CLOZE, QTYPE_SINGLE_CHOICE, QTYPE_JUDGE, QTYPE_MULTIPLE_CHOICE]
        question_types = [_type_cycle[i % len(_type_cycle)] for i in range(count)]
        try:
            session = await create_quiz_session(
                db, conv,
                session_type="class_break",
                title="课间互动小测",
                question_count=count,
                node_ids=[t.id for t in targets[:count]],
                question_types=question_types,
            )
            session_data = session_to_client_response(db, session)
            # 记录到消息历史
            db.add(Message(
                conversation_id=conv.id,
                role="assistant",
                type="quiz_session",
                content=json.dumps({"session_id": session.id, "count": count}, ensure_ascii=False),
            ))
            db.commit()
            actual_count = len(session_data["questions"])
            yield {
                "kind": "quiz_session",
                "session_id": session.id,
                "title": session.title,
                "count": actual_count,
                "questions": session_data["questions"],
                "generation_errors": session_data.get("generation_errors", []),
                "message": f"课间小测：{actual_count} 道题，全部答完后点提交，我会逐题批改。",
            }
        except (AiGatewayError, ValueError) as e:
            yield {"kind": "error", "message": str(e)}
        return

    # 小测批启动（逐题流水式）
    if intent == "batch_request":
        targets = _pick_quiz_targets(db, conv, context, limit=BATCH_SIZE)
        if not targets:
            async for ev in _gen_text_blocks(db, conv, user_input, context):
                yield ev
            return
        batch = {"node_ids": [t.id for t in targets], "current": 0, "total": len(targets), "results": []}
        try:
            yield await _emit_quiz(db, conv, targets[0], batch=batch)
        except (AiGatewayError, ValueError) as e:
            yield {"kind": "error", "message": str(e)}
        return

    # 单题流
    if intent == "quiz_request":
        targets = _pick_quiz_targets(db, conv, context, limit=1)
        if targets:
            try:
                yield await _emit_quiz(db, conv, targets[0])
            except (AiGatewayError, ValueError) as e:
                yield {"kind": "error", "message": str(e)}
            return

    # 背诵题流：用户要求背诵/记忆某个知识点
    if intent == "recite_request":
        targets = _pick_quiz_targets(db, conv, context, limit=1)
        if targets:
            try:
                yield await _emit_quiz(db, conv, targets[0], force_type="recite")
            except (AiGatewayError, ValueError) as e:
                yield {"kind": "error", "message": str(e)}
            return
        # 没有可选知识点时，提示用户先选择知识点
        yield {
            "kind": "text",
            "content": "请先在知识树中选择一个要背诵的知识点，或者告诉我你想背什么内容，我来帮你生成背诵卡片。",
        }
        return

    # 讲解流（默认）
    async for ev in _gen_text_blocks(db, conv, user_input, context):
        yield ev