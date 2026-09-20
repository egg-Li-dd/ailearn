"""学习会话与任务 API。"""
import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_db
from ..models import Course, ScheduleItem, StudySession, Task
from ..models.enums import TaskStatus
from ..schemas.session import SessionOut, TaskCreate, TaskOut
from ..services import task_center
from ..services.planner import plan_session
from ..services.scheduler import tick_once
from ..services.session_service import ensure_today_sessions, session_time_range
from ..services.task_quiz import ensure_task_quiz, submit_task_quiz_result

router = APIRouter(prefix="/api/v1", tags=["session"])


def _get_session_or_404(db: Session, session_id: int) -> StudySession:
    s = db.get(StudySession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


def _to_out(db: Session, s: StudySession) -> SessionOut:
    course = db.get(Course, s.course_id)
    tasks = list(
        db.scalars(select(Task).where(Task.session_id == s.id).order_by(Task.seq, Task.id))
    )
    rng = session_time_range(db, s)
    schedule_meta = db.scalar(
        select(ScheduleItem)
        .where(
            ScheduleItem.course_id == s.course_id,
            ScheduleItem.weekday == s.date.weekday(),
            ScheduleItem.is_active.is_(True),
        )
        .order_by(ScheduleItem.start_time)
        .limit(1)
    )
    return SessionOut(
        id=s.id,
        course_id=s.course_id,
        course_name=course.name if course else f"#{s.course_id}",
        date=s.date,
        status=s.status,
        start_time=rng[0].time() if rng else None,
        end_time=rng[1].time() if rng else None,
        location=schedule_meta.location if schedule_meta else None,
        teacher=schedule_meta.teacher if schedule_meta else None,
        classroom=schedule_meta.classroom if schedule_meta else None,
        tasks=[TaskOut.model_validate(t) for t in tasks],
    )


def _next_seq(db: Session, session_id: int) -> int:
    last = db.scalar(
        select(Task.seq).where(Task.session_id == session_id).order_by(Task.seq.desc()).limit(1)
    )
    return (last or 0) + 1


@router.post("/debug/tick")
async def debug_tick():
    """开发辅助：手动触发一次状态机推进（正式发布前移除）。"""
    changes = await tick_once()
    return [
        {"session_id": c.session_id, "old_status": c.old, "new_status": c.new}
        for c in changes
    ]


@router.get("/sessions/today", response_model=list[SessionOut])
def sessions_today(db: Session = Depends(get_db)):
    sessions = ensure_today_sessions(db)
    return [_to_out(db, s) for s in sessions]


@router.get("/sessions", response_model=list[SessionOut])
def sessions_by_date(date: date, db: Session = Depends(get_db)):
    """按日期查询会话（含任务）。date 格式 YYYY-MM-DD；自动确保该日会话已生成。"""
    sessions = ensure_today_sessions(db, day=date)
    return [_to_out(db, s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionOut)
def session_detail(session_id: int, db: Session = Depends(get_db)):
    return _to_out(db, _get_session_or_404(db, session_id))


async def _execute_plan_session(session_id: int):
    """后台执行会话规划。"""
    db = SessionLocal()
    try:
        s = db.get(StudySession, session_id)
        if not s:
            task_center.fail_task(error="会话不存在")
            return
        course = db.get(Course, s.course_id)
        course_name = course.name if course else f"#{s.course_id}"

        task_center.update_progress(stage=f"正在为「{course_name}」规划任务...", progress=30)
        tasks = await plan_session(db, s)
        task_center.update_progress(progress=100)
        task_center.complete_task(result={
            "session_id": session_id,
            "task_count": len(tasks),
            "redirect": f"/sessions/{session_id}",
        })
    except Exception as e:
        task_center.fail_task(error=str(e))
    finally:
        db.close()


@router.post("/sessions/{session_id}/plan")
async def plan_tasks(session_id: int, db: Session = Depends(get_db)):
    """规划 Agent：为会话生成任务清单（后台任务）。立即返回 task_id。"""
    s = _get_session_or_404(db, session_id)
    course = db.get(Course, s.course_id)
    course_name = course.name if course else f"#{s.course_id}"

    task_id = task_center.create_task(
        task_type="plan_session",
        title=f"会话规划：{course_name} {s.date}",
        metadata={"session_id": session_id},
    )
    token = task_center._current_task_id.set(task_id)
    try:
        task_center.mark_running(task_id)
        asyncio.create_task(_execute_plan_session(session_id))
    finally:
        task_center._current_task_id.reset(token)
    return {"task_id": task_id, "status": "pending", "message": "会话规划任务已创建"}


@router.post("/sessions/{session_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(session_id: int, payload: TaskCreate, db: Session = Depends(get_db)):
    s = _get_session_or_404(db, session_id)
    task = Task(
        session_id=s.id,
        seq=_next_seq(db, s.id),
        type=payload.type,
        title=payload.title,
        est_minutes=payload.est_minutes,
        target_knowledge_id=payload.target_knowledge_id,
        status=TaskStatus.TODO,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.quiz_session_id is not None and not task.passed:
        raise HTTPException(
            status_code=400,
            detail=f"该任务需要通过检测题才能完成（当前得分 {task.actual_score or 0}/{task.pass_score}）"
        )
    task.status = TaskStatus.DONE
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/skip", response_model=TaskOut)
def skip_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.status = TaskStatus.SKIPPED
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


# ---------- 任务-检测闭环 ----------


class TaskQuizAnswer(BaseModel):
    question_id: int
    user_answer: str


class TaskQuizSubmitRequest(BaseModel):
    answers: list[TaskQuizAnswer]


@router.post("/tasks/{task_id}/ensure-quiz")
async def ensure_task_quiz_endpoint(task_id: int, db: Session = Depends(get_db)):
    """确保任务有关联的检测题；没有则生成。返回检测题会话数据。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = await ensure_task_quiz(db, task)
    if result is None:
        raise HTTPException(status_code=400, detail="该任务未绑定知识点，无法生成检测题")
    return result


@router.post("/tasks/{task_id}/submit-quiz")
async def submit_task_quiz_endpoint(
    task_id: int,
    payload: TaskQuizSubmitRequest,
    db: Session = Depends(get_db),
):
    """提交任务检测题答案，判卷后更新任务状态（通过→DONE，未通过→保持TODO）。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.quiz_session_id is None:
        raise HTTPException(status_code=400, detail="该任务尚未生成检测题，请先调用 ensure-quiz")

    from ..models import QuizSession
    from ..services.quiz_session import submit_answers

    session = db.get(QuizSession, task.quiz_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="检测题会话不存在")

    answers = [a.model_dump() for a in payload.answers]
    result = await submit_answers(db, session, answers)

    results = result.get("results", [])
    if results:
        correct = sum(1 for r in results if r.get("correct") is True)
        score = int(correct / len(results) * 100)
    else:
        score = 0

    passed = score >= task.pass_score
    completion_result = submit_task_quiz_result(db, task, score, passed)

    db.refresh(task)
    return {
        "task": TaskOut.model_validate(task),
        "quiz_result": result,
        "score": score,
        "passed": task.passed,
        "pass_score": task.pass_score,
        "completion": task.completion,
        "best_score": task.best_score,
        "auto_completed": completion_result.get("auto_completed", False),
    }


@router.post("/tasks/{task_id}/complete-by-mastery")
def complete_task_by_mastery(task_id: int, db: Session = Depends(get_db)):
    """用掌握度完成任务（前提：target_knowledge_id 的 mastery >= 80）。"""
    from ..services.task_completion import complete_by_mastery

    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = complete_by_mastery(db, task)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    db.refresh(task)
    return {
        "task": TaskOut.model_validate(task),
        "mastery": result.get("mastery"),
        "completion": result.get("completion"),
        "message": result["message"],
    }


@router.get("/tasks/{task_id}/completion")
def get_task_completion(task_id: int, db: Session = Depends(get_db)):
    """获取任务完成度详情。"""
    from ..services.task_completion import update_task_completion

    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = update_task_completion(db, task)
    db.refresh(task)
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
        "completion": task.completion,
        "mastery": result["mastery"],
        "best_score": result["best_score"],
        "participation": result["participation"],
        "attempts": task.attempts,
        "pass_score": task.pass_score,
        "actual_score": task.actual_score,
        "score_history": task.score_history,
        "can_complete_by_mastery": result["mastery"] >= 80 and task.target_knowledge_id is not None,
    }
