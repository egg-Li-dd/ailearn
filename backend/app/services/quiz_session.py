"""测验会话服务（批量出题/统一提交/重做）。

对应需求：
- 多题同时出（创建 session，一次生成多题）
- 所有答案出完统一纠错（submit，逐题判卷后统一返回）
- 一键重做/单题重做（redo，重置作答，题目和解析复用）
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Conversation, KnowledgeNode, QuizAnswer, QuizQuestion,
    QuizSession, QuizSessionItem,
)
from .ai_gateway import AiGatewayError
from .quiz import generate_question, grade_answer, load_payload
from .quiz_contract import (
    QTYPE_SINGLE_CHOICE, QTYPE_FILL_CLOZE, QTYPE_JUDGE,
    sanitize_for_client,
)

logger = logging.getLogger("ailearn.quiz_session")


async def create_session(
    db: Session,
    conv: Conversation,
    *,
    session_type: str = "class_break",
    title: str | None = None,
    question_count: int = 5,
    node_ids: list[int] | None = None,
    question_types: list[str] | None = None,
) -> QuizSession:
    """创建测验会话并批量出题。

    Args:
        session_type: single / batch / class_break
        title: 会话标题（如"课间小测：二叉树遍历"）
        question_count: 题目数量
        node_ids: 指定知识点 ID 列表，None 则从当前课程的薄弱节点选
        question_types: 强制题型分布，None 则按掌握度自动选
    """
    # 选题目标节点
    targets = _pick_target_nodes(db, conv, node_ids, question_count)
    if not targets:
        raise ValueError("没有可用的知识点，请先在知识树中添加节点")

    # 创建会话
    session = QuizSession(
        conversation_id=conv.id,
        session_type=session_type,
        status="awaiting_submit",
        current_attempt=1,
        title=title,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # 逐题生成
    generated = []
    generation_errors = []
    for i, node in enumerate(targets[:question_count]):
        force_type = None
        if question_types and i < len(question_types):
            force_type = question_types[i]
        try:
            # AI优先，AI失败时fallback到模板（use_template=True）
            q = await generate_question(db, node.id, force_type=force_type, use_template=True)
            item = QuizSessionItem(session_id=session.id, question_id=q.id, seq=i)
            db.add(item)
            generated.append(q)
        except (AiGatewayError, ValueError) as e:
            error_msg = str(e)
            logger.warning("create_session: 生成第%d题失败(node=%s): %s", i, node.name, error_msg)
            generation_errors.append({
                "seq": i,
                "node_id": node.id,
                "node_name": node.name,
                "error": error_msg,
            })
            continue

    db.commit()

    if not generated:
        db.delete(session)
        db.commit()
        raise ValueError("所有题目生成失败，请重试")

    # 记录出题失败信息（如果有）
    if generation_errors:
        session.generation_errors = json.dumps(generation_errors, ensure_ascii=False)
        db.commit()

    # 绑定到会话
    conv.active_quiz_session_id = session.id
    conv.active_quiz_id = None  # 退出单题模式
    db.commit()

    return session


def get_session_questions(db: Session, session_id: int) -> list[tuple[QuizSessionItem, QuizQuestion]]:
    """获取会话的题目列表（按 seq 排序）。"""
    items = list(
        db.scalars(
            select(QuizSessionItem)
            .where(QuizSessionItem.session_id == session_id)
            .order_by(QuizSessionItem.seq)
        )
    )
    result = []
    for item in items:
        q = db.get(QuizQuestion, item.question_id)
        if q:
            result.append((item, q))
    return result


def session_to_client_response(db: Session, session: QuizSession) -> dict:
    """将会话+题目转为前端响应（脱敏，不含答案）。"""
    questions = []
    for item, q in get_session_questions(db, session.id):
        payload = load_payload(q)
        safe = sanitize_for_client(payload)
        safe["id"] = q.id
        safe["seq"] = item.seq
        safe["difficulty"] = q.difficulty
        questions.append(safe)

    resp = {
        "session_id": session.id,
        "status": session.status,
        "title": session.title,
        "current_attempt": session.current_attempt,
        "questions": questions,
    }

    # 返回出题失败信息（如果有）
    if session.generation_errors:
        try:
            resp["generation_errors"] = json.loads(session.generation_errors)
        except (json.JSONDecodeError, TypeError):
            pass

    # awaiting_submit 状态下返回草稿答案（前端可恢复作答痕迹）
    if session.status == "awaiting_submit":
        drafts = get_draft_answers(db, session.id)
        if drafts:
            resp["draft_answers"] = {str(k): v for k, v in drafts.items()}

    # graded 状态下附带判卷结果（前端直接回显对错）
    if session.status == "graded":
        results = []
        for item, q in get_session_questions(db, session.id):
            ans = db.scalar(
                select(QuizAnswer)
                .where(
                    QuizAnswer.session_id == session.id,
                    QuizAnswer.question_id == q.id,
                    QuizAnswer.attempt == session.current_attempt,
                )
                .order_by(QuizAnswer.id.desc())
                .limit(1)
            )
            if ans:
                try:
                    graded = json.loads(ans.ai_feedback) if ans.ai_feedback else {}
                except (json.JSONDecodeError, TypeError):
                    graded = {}
                graded["question_id"] = q.id
                graded["score"] = ans.score
                graded["user_answer"] = ans.user_answer
                payload = load_payload(q)
                graded["question"] = payload.get("question", "")
                graded["standard_answer"] = payload.get("correct_answer", "")
                graded["explanation"] = payload.get("explanation", "")
                results.append(graded)
            else:
                results.append({
                    "question_id": q.id,
                    "correct": False,
                    "score": 0,
                    "unanswered": True,
                    "question": load_payload(q).get("question", ""),
                    "user_answer": "",
                })
        resp["results"] = results
        correct_count = sum(1 for r in results if r.get("correct") is True)
        resp["correct_count"] = correct_count
        resp["total_count"] = len(results)
        # 计算总分和百分比
        total_score = sum(r.get("score", 0) for r in results)
        max_score = sum(r.get("max_points", 1) * 100 for r in results)
        score_percent = int(total_score / max_score * 100) if max_score > 0 else 0
        resp["total_score"] = total_score
        resp["max_score"] = max_score
        resp["score_percent"] = score_percent
        # 等级
        if score_percent >= 90:
            resp["grade"] = "优秀"
            resp["grade_emoji"] = "🏆"
        elif score_percent >= 75:
            resp["grade"] = "良好"
            resp["grade_emoji"] = "👍"
        elif score_percent >= 60:
            resp["grade"] = "及格"
            resp["grade_emoji"] = "💪"
        else:
            resp["grade"] = "需努力"
            resp["grade_emoji"] = "📚"
        # 用户反馈
        resp["feedback"] = _generate_session_feedback(score_percent, correct_count, len(results), results)

    return resp


async def submit_answers(
    db: Session,
    session: QuizSession,
    answers: list[dict],
) -> dict:
    """统一提交答案并逐题判卷，返回汇总结果。

    支持单题重做：如果提交的 answers 数量 < session 题目总数，
    未提交的题目沿用最近一次 attempt 的判卷结果。

    Args:
        answers: [{"question_id": 101, "user_answer": {...}}, ...]
    """
    if session.status != "awaiting_submit":
        raise ValueError(f"会话状态不允许提交: {session.status}")

    session.status = "grading"
    db.commit()

    answer_map = {a["question_id"]: a.get("user_answer") for a in answers}
    all_questions = get_session_questions(db, session.id)
    is_partial = len(answer_map) < len(all_questions)

    results = []
    total_score = 0
    max_score = 0
    correct_count = 0

    for item, q in all_questions:
        if q.id in answer_map:
            # 本次提交的题目：正常判卷
            user_answer_raw = answer_map[q.id]
            if isinstance(user_answer_raw, (dict, list)):
                user_answer_str = json.dumps(user_answer_raw, ensure_ascii=False)
            else:
                user_answer_str = str(user_answer_raw) if user_answer_raw is not None else ""

            try:
                answer_record = await grade_answer(
                    db, q.id, user_answer_str,
                    session_id=session.id,
                    attempt=session.current_attempt,
                )
                try:
                    graded = json.loads(answer_record.ai_feedback)
                except (json.JSONDecodeError, TypeError):
                    graded = {
                        "correct": None, "score": answer_record.score or 0,
                        "explanation": "", "user_answer": user_answer_raw,
                    }
            except (AiGatewayError, ValueError) as e:
                logger.error("submit_answers: 题目%d判卷失败: %s", q.id, e)
                graded = {
                    "correct": False, "score": 0, "explanation": f"判卷失败: {e}",
                    "user_answer": user_answer_raw, "error": str(e),
                }
        else:
            # 未提交的题目（单题重做场景）：沿用上次 attempt 的结果
            graded = _get_previous_result(db, session.id, q.id, session.current_attempt)
            if graded is None:
                # 没有上次记录，视为未作答（0分）
                graded = {
                    "correct": False, "score": 0,
                    "explanation": "未作答",
                    "user_answer": "",
                    "blank_results": [],
                }

        graded["question_id"] = q.id
        graded["seq"] = item.seq
        payload = load_payload(q)
        graded["type"] = payload.get("type")
        graded["question"] = payload.get("question")
        if "explanation" not in graded or not graded["explanation"]:
            graded["explanation"] = payload.get("explanation", "")
        graded["analysis"] = payload.get("analysis")
        if is_partial and q.id not in answer_map:
            graded["reused_from_previous"] = True  # 标记为沿用上次结果

        results.append(graded)
        total_score += graded.get("score", 0)
        max_score += graded.get("max_points", 1) * 100
        if graded.get("correct") is True:
            correct_count += 1

    session.status = "graded"
    session.finished_at = datetime.now(timezone.utc)
    db.commit()

    # 提交成功后清除草稿答案
    clear_draft_answers(db, session.id)

    # 计算百分比分数和等级
    score_percent = int(total_score / max_score * 100) if max_score > 0 else 0
    if score_percent >= 90:
        grade = "优秀"
        grade_emoji = "🏆"
    elif score_percent >= 75:
        grade = "良好"
        grade_emoji = "👍"
    elif score_percent >= 60:
        grade = "及格"
        grade_emoji = "💪"
    else:
        grade = "需努力"
        grade_emoji = "📚"

    # 生成用户反馈
    feedback = _generate_session_feedback(score_percent, correct_count, len(results), results)

    # 任务联动：如果这个小测会话关联了任务检测题，判卷后自动更新任务状态
    task_info = None
    if session.session_type == "task_check":
        from ..models import Task
        from .task_quiz import submit_task_quiz_result
        task = db.query(Task).filter(Task.quiz_session_id == session.id).first()
        if task:
            # 计算得分（百分制）
            score_percent = int(total_score / max_score * 100) if max_score > 0 else 0
            passed = score_percent >= (task.pass_score or 80)
            completion_result = submit_task_quiz_result(db, task, score_percent, passed)
            db.refresh(task)
            task_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
            task_info = {
                "task_id": task.id,
                "task_title": task.title,
                "passed": task.passed,
                "score": score_percent,
                "best_score": task.best_score,
                "completion": task.completion,
                "pass_score": task.pass_score or 80,
                "status": task_status,
                "attempts": task.attempts,
                "auto_completed": completion_result.get("auto_completed", False),
                "completed_by": completion_result.get("completed_by"),
            }
            logger.info("任务检测题判卷完成: task=%d, score=%d, completion=%d, passed=%s",
                        task.id, score_percent, task.completion, task.passed)

            # 任务相关的学习建议
            if task.passed and task_status == "done":
                feedback["suggestions"].insert(0, f"✅ 任务「{task.title}」已完成！（完成度{task.completion}%）")
            elif completion_result.get("auto_completed"):
                feedback["suggestions"].insert(0, f"✅ 任务「{task.title}」完成度达标，已自动完成！（完成度{task.completion}%）")
            else:
                feedback["suggestions"].insert(0, f"📊 任务「{task.title}」完成度 {task.completion}%（最高分{task.best_score}分），继续努力！")
                feedback["suggestions"].insert(1, "可以复习知识点提升掌握度，或重做检测题提高分数")
            # 更新鼓励语
            if task.passed:
                feedback["encouragement"] = f"恭喜！任务「{task.title}」已完成。" + feedback["encouragement"]
            else:
                feedback["encouragement"] = f"任务「{task.title}」完成度 {task.completion}%，" + feedback["encouragement"]

    return {
        "session_id": session.id,
        "status": "graded",
        "attempt": session.current_attempt,
        "total_score": total_score,
        "max_score": max_score,
        "score_percent": score_percent,
        "grade": grade,
        "grade_emoji": grade_emoji,
        "correct_count": correct_count,
        "total_count": len(results),
        "partial_submit": is_partial,
        "feedback": feedback,
        "task": task_info,  # 任务联动信息（如果是任务检测题）
        "results": results,
    }


def _generate_session_feedback(
    score_percent: int,
    correct_count: int,
    total_count: int,
    results: list[dict],
) -> dict:
    """根据答题情况生成用户反馈（鼓励性话语 + 学习建议）。"""
    # 收集错题的知识点和错误分析
    wrong_questions = []
    knowledge_points = []
    for r in results:
        if r.get("correct") is not True:
            wrong_questions.append(r)
            if r.get("question"):
                # 简单提取知识点（题干前20字）
                knowledge_points.append(r["question"][:30])

    # 鼓励性话语
    if score_percent >= 90:
        encouragement = "太棒了！你已经完全掌握了这些知识点，继续保持！"
    elif score_percent >= 75:
        encouragement = "做得不错！大部分知识点已经掌握，再巩固一下错题就更好了。"
    elif score_percent >= 60:
        encouragement = "及格了！基础还可以，但还有提升空间，重点复习错题。"
    else:
        encouragement = "别灰心！这次没考好没关系，找到薄弱点重点复习，下次一定能进步。"

    # 学习建议
    suggestions = []
    if wrong_questions:
        suggestions.append(f"本次答错 {len(wrong_questions)} 道题，建议重点复习相关知识点")
        # 收集错误分析中的改进建议
        improvement_suggestions = []
        for r in wrong_questions:
            imp = r.get("improvement_suggestion")
            if imp and imp not in improvement_suggestions:
                improvement_suggestions.append(imp)
        if improvement_suggestions:
            suggestions.extend(improvement_suggestions[:2])
        else:
            suggestions.append("建议重新学习错题对应的知识点，理解概念后再做题")
    else:
        suggestions.append("全部答对！可以尝试更难的题目挑战自己")

    if score_percent < 60:
        suggestions.append("建议回到知识点讲解页面，重新学习核心概念")

    return {
        "encouragement": encouragement,
        "suggestions": suggestions,
        "wrong_count": len(wrong_questions),
        "correct_count": correct_count,
        "total_count": total_count,
    }


def _get_previous_result(
    db: Session, session_id: int, question_id: int, current_attempt: int
) -> dict | None:
    """从最近一次 attempt（< current_attempt）的 QuizAnswer 中获取判卷结果。"""
    prev = db.scalar(
        select(QuizAnswer)
        .where(
            QuizAnswer.session_id == session_id,
            QuizAnswer.question_id == question_id,
            QuizAnswer.attempt < current_attempt,
        )
        .order_by(QuizAnswer.attempt.desc())
        .limit(1)
    )
    if not prev:
        return None
    try:
        graded = json.loads(prev.ai_feedback)
        return graded
    except (json.JSONDecodeError, TypeError):
        return {
            "correct": None,
            "score": prev.score or 0,
            "explanation": "",
            "user_answer": prev.user_answer,
        }


def redo_session(
    db: Session,
    session: QuizSession,
    question_ids: list[int] | None = None,
) -> dict:
    """重做（一键重做全部或单题重做）。

    关键：题目和静态解析从 DB 直接复用，不重新调用 AI 出题。
    只重置作答状态，attempt + 1。

    Args:
        question_ids: 要重做的题目 ID 列表。None/空=全部重做。
    """
    if session.status != "graded":
        raise ValueError(f"只有已判卷的会话才能重做，当前状态: {session.status}")

    session.current_attempt += 1
    session.status = "awaiting_submit"
    session.finished_at = None
    db.commit()

    # 返回题目（脱敏），前端清空作答区
    return session_to_client_response(db, session)


def _pick_target_nodes(
    db: Session, conv: Conversation, node_ids: list[int] | None, limit: int
) -> list[KnowledgeNode]:
    """选题目标节点。

    优先用户指定的 node_ids；否则从当前课程的薄弱节点选。
    """
    if node_ids:
        nodes = []
        for nid in node_ids:
            n = db.get(KnowledgeNode, nid)
            if n:
                nodes.append(n)
        if nodes:
            return nodes[:limit]

    # 从会话关联的课程选薄弱节点
    session_id = conv.session_id
    if session_id:
        from ..models import StudySession, Course
        ss = db.get(StudySession, session_id)
        if ss and ss.course_id:
            nodes = list(
                db.scalars(
                    select(KnowledgeNode)
                    .where(KnowledgeNode.subject_id == ss.course_id, KnowledgeNode.level >= 3)
                    .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
                    .limit(limit)
                )
            )
            if nodes:
                return nodes

    # 兜底：全局掌握度最低的节点
    nodes = list(
        db.scalars(
            select(KnowledgeNode)
            .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
            .limit(limit)
        )
    )
    return nodes


def get_active_session(db: Session, conv: Conversation) -> QuizSession | None:
    """获取当前活跃的测验会话。"""
    if conv.active_quiz_session_id:
        return db.get(QuizSession, conv.active_quiz_session_id)
    return None


# ---------------------------------------------------------------------------
# 草稿答案（答题过程中实时保存，刷新页面后可恢复）
# ---------------------------------------------------------------------------

def save_draft_answer(
    db: Session, session_id: int, question_id: int, user_answer: str
) -> None:
    """保存单题草稿答案（attempt=0 表示草稿，不参与判卷）。

    每次保存前删除该题已有的草稿，确保一题只有一份最新草稿。
    """
    # 删除该题已有的草稿
    old = db.scalars(
        select(QuizAnswer).where(
            QuizAnswer.session_id == session_id,
            QuizAnswer.question_id == question_id,
            QuizAnswer.attempt == 0,
        )
    ).all()
    for o in old:
        db.delete(o)

    # 空答案不保存（表示清空）
    if not user_answer or not str(user_answer).strip():
        db.commit()
        return

    draft = QuizAnswer(
        question_id=question_id,
        session_id=session_id,
        attempt=0,
        user_answer=str(user_answer),
        score=None,
        ai_feedback=None,
    )
    db.add(draft)
    db.commit()


def get_draft_answers(db: Session, session_id: int) -> dict[int, str]:
    """获取会话的所有草稿答案，返回 {question_id: user_answer}。"""
    drafts = db.scalars(
        select(QuizAnswer).where(
            QuizAnswer.session_id == session_id,
            QuizAnswer.attempt == 0,
        )
    ).all()
    return {d.question_id: d.user_answer for d in drafts}


def clear_draft_answers(db: Session, session_id: int) -> None:
    """提交成功后清除所有草稿答案。"""
    drafts = db.scalars(
        select(QuizAnswer).where(
            QuizAnswer.session_id == session_id,
            QuizAnswer.attempt == 0,
        )
    ).all()
    for d in drafts:
        db.delete(d)
    db.commit()
