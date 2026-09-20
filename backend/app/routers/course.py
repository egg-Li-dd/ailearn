"""课程、周课表、例外 CRUD（含时间冲突检测、网格视图、模板、月历）。"""
import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Course, KnowledgeNode, ScheduleException, ScheduleItem, ScheduleTemplate, StudySession
from ..schemas.course import (
    ConflictOut,
    CourseArchiveRequest,
    CourseBatchDelete,
    CourseCreate,
    CourseOut,
    CourseSortItem,
    CourseSummaryOut,
    CourseUpdate,
    ExceptionBatchDelete,
    ExceptionBatchImport,
    ExceptionCalendarOut,
    ScheduleExceptionCreate,
    ScheduleExceptionOut,
    ScheduleExceptionUpdate,
    ScheduleGridOut,
    ScheduleItemCreate,
    ScheduleItemMoveRequest,
    ScheduleItemOut,
    ScheduleItemUpdate,
    ScheduleTemplateCreate,
    ScheduleTemplateOut,
)
from ..services.audit_service import log as audit_log

router = APIRouter(prefix="/api/v1", tags=["course"])


def _get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{label} 不存在")
    return obj


def _conflict(db: Session, weekday: int, start: time, end: time, exclude_id: int | None = None) -> ScheduleItem | None:
    stmt = select(ScheduleItem).where(
        ScheduleItem.weekday == weekday,
        ScheduleItem.is_active.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(ScheduleItem.id != exclude_id)
    for item in db.scalars(stmt):
        if start < item.end_time and item.start_time < end:
            return item
    return None


def _course_name(db: Session, course_id: int | None) -> str | None:
    if course_id is None:
        return None
    c = db.get(Course, course_id)
    return c.name if c else None


# ==================== 科目 ====================

@router.get("/courses", response_model=list[CourseOut])
def list_courses(
    archived: str | None = None,
    search: str | None = None,
    has_schedule: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Course)
    if archived is not None and archived != "all":
        stmt = stmt.where(Course.is_archived == (archived == "true"))
    if search:
        keyword = f"%{search}%"
        stmt = stmt.where((Course.name.like(keyword)) | (Course.subject_code.like(keyword)))
    courses = list(db.scalars(stmt.order_by(Course.sort, Course.id)))
    if has_schedule is not None and has_schedule != "all":
        target = has_schedule == "true"
        result = []
        for c in courses:
            count = db.scalar(select(ScheduleItem.id).where(ScheduleItem.course_id == c.id).limit(1))
            has = count is not None
            if has == target:
                result.append(c)
        return result
    return courses


@router.post("/courses", response_model=CourseOut, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)):
    course = Course(**payload.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    audit_log(db, "course", "create", course.id, course.name, {"color": course.color})
    return course


@router.put("/courses/{course_id}", response_model=CourseOut)
def update_course(course_id: int, payload: CourseUpdate, db: Session = Depends(get_db)):
    course = _get_or_404(db, Course, course_id, "科目")
    old_name = course.name
    # 记录所有字段变更（含学习目标），用于审计追溯
    changes: dict = {}
    for k, v in payload.model_dump(exclude_unset=True).items():
        old_val = getattr(course, k, None)
        if old_val != v:
            changes[k] = {"old": str(old_val) if old_val is not None else None,
                           "new": str(v) if v is not None else None}
        setattr(course, k, v)
    db.commit()
    db.refresh(course)
    extra = {"old_name": old_name}
    if changes:
        extra["changes"] = changes
    audit_log(db, "course", "update", course.id, course.name, extra)
    return course


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = _get_or_404(db, Course, course_id, "科目")
    has_items = db.scalar(select(ScheduleItem.id).where(ScheduleItem.course_id == course_id).limit(1))
    if has_items:
        raise HTTPException(status_code=409, detail="该科目下存在课表项，请先移除课表项")
    name = course.name
    db.delete(course)
    db.commit()
    audit_log(db, "course", "delete", course_id, name, {})


@router.put("/courses/{course_id}/archive", response_model=CourseOut)
def archive_course(course_id: int, payload: CourseArchiveRequest, db: Session = Depends(get_db)):
    course = _get_or_404(db, Course, course_id, "科目")
    course.is_archived = payload.is_archived
    db.commit()
    db.refresh(course)
    audit_log(db, "course", "archive", course.id, course.name, {"is_archived": payload.is_archived})
    return course


@router.put("/courses/sort")
def sort_courses(payload: list[CourseSortItem], db: Session = Depends(get_db)):
    for item in payload:
        course = db.get(Course, item.id)
        if course:
            course.sort = item.sort
    db.commit()
    if payload:
        audit_log(db, "course", "sort", None, "批量排序", {"count": len(payload)})
    return {"updated": len(payload)}


@router.get("/courses/{course_id}/summary", response_model=CourseSummaryOut)
def course_summary(course_id: int, db: Session = Depends(get_db)):
    course = _get_or_404(db, Course, course_id, "科目")
    schedule_count = db.scalar(select(func.count(ScheduleItem.id)).where(ScheduleItem.course_id == course_id)) or 0

    # === 统一基于叶子节点（level>=3）统计，避免与饼图口径不一致 ===
    leaf_nodes = list(db.scalars(
        select(KnowledgeNode).where(
            KnowledgeNode.subject_id == course_id,
            KnowledgeNode.level >= 3,
        )
    ))
    knowledge_count = len(leaf_nodes)
    avg_mastery = (sum(n.mastery for n in leaf_nodes) / knowledge_count) if leaf_nodes else 0.0

    sessions = list(db.scalars(
        select(StudySession).where(StudySession.course_id == course_id).order_by(StudySession.date.desc()).limit(5)
    ))

    # === 掌握状态分布 ===
    dist = {"mastered": 0, "learning": 0, "untouched": 0, "review": 0}
    for n in leaf_nodes:
        if n.status == "review":
            dist["review"] += 1
        elif n.mastery >= 80:
            dist["mastered"] += 1
        elif n.status == "learning" or n.mastery > 0:
            dist["learning"] += 1
        else:
            dist["untouched"] += 1

    # === 每日目标知识点数（含待复习，上限50避免数字失真） ===
    daily_target = None
    if course.target_days is not None and course.days_remaining is not None and course.days_remaining > 0:
        unmastered = dist["learning"] + dist["untouched"] + dist["review"]
        import math
        daily_target = max(1, min(50, math.ceil(unmastered / course.days_remaining)))

    return CourseSummaryOut(
        id=course.id, name=course.name, subject_code=course.subject_code,
        color=course.color, icon=course.icon, description=course.description,
        schedule_count=schedule_count, knowledge_count=knowledge_count,
        avg_mastery=round(avg_mastery, 1),
        recent_sessions=[{"date": s.date.isoformat(), "status": s.status} for s in sessions],
        target_days=course.target_days,
        goal_start_date=course.goal_start_date,
        days_remaining=course.days_remaining,
        daily_knowledge_target=daily_target,
        mastery_distribution=dist,
    )


@router.delete("/courses/batch")
def batch_delete_courses(payload: CourseBatchDelete, db: Session = Depends(get_db)):
    deleted = 0
    for cid in payload.ids:
        course = db.get(Course, cid)
        if course:
            has_items = db.scalar(select(ScheduleItem.id).where(ScheduleItem.course_id == cid).limit(1))
            if not has_items:
                db.delete(course)
                deleted += 1
    db.commit()
    return {"deleted": deleted, "skipped": len(payload.ids) - deleted}


# ==================== 周课表 ====================

@router.get("/schedule", response_model=list[ScheduleItemOut])
def list_schedule(
    week_type: str | None = None,
    course_id: int | None = None,
    weekday: int | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(ScheduleItem)
    if week_type and week_type != "all":
        stmt = stmt.where(ScheduleItem.week_type.in_(["all", week_type]))
    if course_id is not None:
        stmt = stmt.where(ScheduleItem.course_id == course_id)
    if weekday is not None:
        stmt = stmt.where(ScheduleItem.weekday == weekday)
    if active_only:
        stmt = stmt.where(ScheduleItem.is_active.is_(True))
    return list(db.scalars(stmt.order_by(ScheduleItem.weekday, ScheduleItem.start_time, ScheduleItem.sort)))


@router.post("/schedule", response_model=ScheduleItemOut, status_code=201)
def create_schedule_item(payload: ScheduleItemCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Course, payload.course_id, "科目")
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=422, detail="开始时间必须早于结束时间")
    hit = _conflict(db, payload.weekday, payload.start_time, payload.end_time)
    if hit:
        course = db.get(Course, hit.course_id)
        raise HTTPException(status_code=409, detail={
            "message": f"与「{course.name}」({hit.start_time:%H:%M}-{hit.end_time:%H:%M}) 时间冲突",
            "existing_item_id": hit.id, "existing_course_name": course.name,
        })
    item = ScheduleItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    audit_log(db, "schedule", "create", item.id, f"课表项#{item.id}", {"weekday": item.weekday, "course_id": item.course_id})
    return item


@router.put("/schedule/{item_id}", response_model=ScheduleItemOut)
def update_schedule_item(item_id: int, payload: ScheduleItemUpdate, db: Session = Depends(get_db)):
    item = _get_or_404(db, ScheduleItem, item_id, "课表项")
    data = payload.model_dump(exclude_unset=True)
    if data.get("course_id"):
        _get_or_404(db, Course, data["course_id"], "科目")
    merged = {
        "weekday": data.get("weekday", item.weekday),
        "start_time": data.get("start_time", item.start_time),
        "end_time": data.get("end_time", item.end_time),
        "is_active": data.get("is_active", item.is_active),
    }
    if merged["start_time"] >= merged["end_time"]:
        raise HTTPException(status_code=422, detail="开始时间必须早于结束时间")
    if data.get("is_active", item.is_active):
        hit = _conflict(db, merged["weekday"], merged["start_time"], merged["end_time"], exclude_id=item_id)
        if hit:
            course = db.get(Course, hit.course_id)
            raise HTTPException(status_code=409, detail={
                "message": f"与「{course.name}」({hit.start_time:%H:%M}-{hit.end_time:%H:%M}) 时间冲突",
                "existing_item_id": hit.id, "existing_course_name": course.name,
            })
    for k, v in data.items():
        if k == "is_active" and v is False and not item.is_active:
            continue
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    audit_log(db, "schedule", "update", item.id, f"课表项#{item.id}", {"changed": list(data.keys())})
    return item


@router.delete("/schedule/{item_id}", status_code=204)
def delete_schedule_item(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, ScheduleItem, item_id, "课表项")
    db.delete(item)
    db.commit()
    audit_log(db, "schedule", "delete", item_id, f"课表项#{item_id}", {"weekday": item.weekday})


@router.get("/schedule/grid", response_model=ScheduleGridOut)
def schedule_grid(week_type: str = "all", db: Session = Depends(get_db)):
    """网格视图数据：按星期×时段聚合，含冲突标记。"""
    stmt = select(ScheduleItem).where(ScheduleItem.is_active.is_(True))
    if week_type != "all":
        stmt = stmt.where(ScheduleItem.week_type.in_(["all", week_type]))
    items = list(db.scalars(stmt.order_by(ScheduleItem.weekday, ScheduleItem.start_time, ScheduleItem.sort)))

    # 收集所有时段
    time_set = set()
    for item in items:
        time_set.add(item.start_time.strftime("%H:%M"))
    time_slots = sorted(time_set)

    # 按 weekday + time 分组
    grid: dict = {}
    for item in items:
        wd = str(item.weekday)
        tk = item.start_time.strftime("%H:%M")
        grid.setdefault(wd, {}).setdefault(tk, []).append({
            "id": item.id, "course_id": item.course_id,
            "course_name": _course_name(db, item.course_id),
            "color": db.get(Course, item.course_id).color if item.course_id else None,
            "color_override": item.color_override,
            "start_time": item.start_time.strftime("%H:%M"),
            "end_time": item.end_time.strftime("%H:%M"),
            "location": item.location, "teacher": item.teacher, "classroom": item.classroom,
            "week_type": item.week_type, "sort": item.sort,
        })

    # 检测冲突
    conflicts = []
    for wd, times in grid.items():
        for tk, items_at_time in times.items():
            if len(items_at_time) > 1:
                for it in items_at_time:
                    conflicts.append({
                        "item_id": it["id"], "weekday": int(wd), "time": tk,
                        "conflict_with": [{"id": i["id"], "course_name": i["course_name"]}
                                           for i in items_at_time if i["id"] != it["id"]],
                    })
                    it["has_conflict"] = True

    return ScheduleGridOut(week_type=week_type, time_slots=time_slots, grid=grid, conflicts=conflicts)


@router.put("/schedule/{item_id}/move", response_model=ScheduleItemOut)
def move_schedule_item(item_id: int, payload: ScheduleItemMoveRequest, db: Session = Depends(get_db)):
    """拖拽移动课表项，自动冲突检测。"""
    item = _get_or_404(db, ScheduleItem, item_id, "课表项")
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=422, detail="开始时间必须早于结束时间")
    hit = _conflict(db, payload.weekday, payload.start_time, payload.end_time, exclude_id=item_id)
    if hit:
        course = db.get(Course, hit.course_id)
        raise HTTPException(status_code=409, detail={
            "message": f"与「{course.name}」冲突",
            "existing_item_id": hit.id, "existing_course_name": course.name,
        })
    item.weekday = payload.weekday
    item.start_time = payload.start_time
    item.end_time = payload.end_time
    item.sort = payload.sort
    db.commit()
    db.refresh(item)
    audit_log(db, "schedule", "move", item.id, f"课表项#{item.id}", {"new_weekday": payload.weekday})
    return item


@router.get("/schedule/conflicts")
def list_conflicts(weekday: int | None = None, db: Session = Depends(get_db)):
    """获取所有冲突的课表项。"""
    stmt = select(ScheduleItem).where(ScheduleItem.is_active.is_(True))
    if weekday is not None:
        stmt = stmt.where(ScheduleItem.weekday == weekday)
    items = list(db.scalars(stmt))
    conflicts = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.weekday == b.weekday and a.start_time < b.end_time and b.start_time < a.end_time:
                conflicts.append({
                    "item_a": {"id": a.id, "course_name": _course_name(db, a.course_id),
                               "time": f"{a.start_time:%H:%M}-{a.end_time:%H:%M}"},
                    "item_b": {"id": b.id, "course_name": _course_name(db, b.course_id),
                               "time": f"{b.start_time:%H:%M}-{b.end_time:%H:%M}"},
                    "weekday": a.weekday,
                })
    return {"total": len(conflicts), "conflicts": conflicts}


@router.delete("/schedule/batch")
def batch_delete_schedule(payload: CourseBatchDelete, db: Session = Depends(get_db)):
    deleted = 0
    for iid in payload.ids:
        item = db.get(ScheduleItem, iid)
        if item:
            db.delete(item)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


# ---------- 课表模板 ----------

@router.get("/schedule/templates", response_model=list[ScheduleTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return list(db.scalars(select(ScheduleTemplate).order_by(ScheduleTemplate.created_at.desc())))


@router.post("/schedule/templates", response_model=ScheduleTemplateOut, status_code=201)
def save_template(payload: ScheduleTemplateCreate, db: Session = Depends(get_db)):
    """保存当前所有启用课表项为模板。"""
    items = list(db.scalars(select(ScheduleItem).where(ScheduleItem.is_active.is_(True))))
    items_json = json.dumps([{
        "course_id": i.course_id, "weekday": i.weekday,
        "start_time": i.start_time.isoformat(), "end_time": i.end_time.isoformat(),
        "location": i.location, "teacher": i.teacher, "classroom": i.classroom,
        "week_type": i.week_type, "color_override": i.color_override,
    } for i in items], ensure_ascii=False)
    tpl = ScheduleTemplate(name=payload.name, description=payload.description, items_json=items_json)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.post("/schedule/templates/{template_id}/apply")
def apply_template(template_id: int, db: Session = Depends(get_db)):
    """应用模板：清空现有课表项，从模板恢复。"""
    tpl = _get_or_404(db, ScheduleTemplate, template_id, "模板")
    # 删除现有所有课表项
    db.query(ScheduleItem).delete()
    # 从模板恢复
    items = json.loads(tpl.items_json)
    for it in items:
        item = ScheduleItem(
            course_id=it["course_id"], weekday=it["weekday"],
            start_time=time.fromisoformat(it["start_time"]),
            end_time=time.fromisoformat(it["end_time"]),
            location=it.get("location"), teacher=it.get("teacher"),
            classroom=it.get("classroom"), week_type=it.get("week_type", "all"),
            color_override=it.get("color_override"),
        )
        db.add(item)
    db.commit()
    return {"applied": len(items), "template_name": tpl.name}


@router.delete("/schedule/templates/{template_id}", status_code=204)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    tpl = _get_or_404(db, ScheduleTemplate, template_id, "模板")
    name = tpl.name
    db.delete(tpl)
    db.commit()
    audit_log(db, "schedule_template", "delete", template_id, name, {})


# ==================== 日期例外 ====================

@router.get("/schedule/exceptions", response_model=list[ScheduleExceptionOut])
def list_exceptions(
    start: date | None = None,
    end: date | None = None,
    action: str | None = None,
    course_id: int | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(ScheduleException)
    if start:
        stmt = stmt.where(ScheduleException.date >= start)
    if end:
        stmt = stmt.where(ScheduleException.date <= end)
    if action:
        stmt = stmt.where(ScheduleException.action == action)
    if course_id is not None:
        stmt = stmt.where(ScheduleException.course_id == course_id)
    if active_only:
        stmt = stmt.where(ScheduleException.is_active.is_(True))
    return list(db.scalars(stmt.order_by(ScheduleException.date)))


@router.post("/schedule/exceptions", response_model=ScheduleExceptionOut, status_code=201)
def create_exception(payload: ScheduleExceptionCreate, db: Session = Depends(get_db)):
    if payload.action == "add" and payload.course_id is not None:
        _get_or_404(db, Course, payload.course_id, "科目")
    exc = ScheduleException(**payload.model_dump())
    db.add(exc)
    db.commit()
    db.refresh(exc)
    audit_log(db, "exception", "create", exc.id, f"例外#{exc.id}", {"date": str(exc.date), "action": exc.action})
    return exc


@router.put("/schedule/exceptions/{exc_id}", response_model=ScheduleExceptionOut)
def update_exception(exc_id: int, payload: ScheduleExceptionUpdate, db: Session = Depends(get_db)):
    exc = _get_or_404(db, ScheduleException, exc_id, "例外")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(exc, k, v)
    db.commit()
    db.refresh(exc)
    audit_log(db, "exception", "update", exc.id, f"例外#{exc.id}", {"changed": list(payload.model_dump(exclude_unset=True).keys())})
    return exc


@router.delete("/schedule/exceptions/{exc_id}", status_code=204)
def delete_exception(exc_id: int, db: Session = Depends(get_db)):
    exc = _get_or_404(db, ScheduleException, exc_id, "例外")
    db.delete(exc)
    db.commit()
    audit_log(db, "exception", "delete", exc_id, f"例外#{exc_id}", {"date": str(exc.date)})


@router.get("/schedule/exceptions/calendar", response_model=ExceptionCalendarOut)
def exceptions_calendar(year: int, month: int, db: Session = Depends(get_db)):
    """月历视图数据：按日期聚合。"""
    import calendar
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    exceptions = list(db.scalars(
        select(ScheduleException).where(
            ScheduleException.date >= first_day,
            ScheduleException.date <= last_day,
            ScheduleException.is_active.is_(True),
        ).order_by(ScheduleException.date)
    ))

    days: dict = {}
    remove_count = 0
    add_count = 0
    for exc in exceptions:
        d = exc.date.day
        if d not in days:
            days[d] = {"date": exc.date.isoformat(), "weekday": exc.date.weekday(),
                       "exceptions": [], "has_remove": False, "has_add": False}
        entry = {
            "id": exc.id, "action": exc.action,
            "course_name": _course_name(db, exc.course_id),
            "start_time": exc.start_time.strftime("%H:%M") if exc.start_time else None,
            "end_time": exc.end_time.strftime("%H:%M") if exc.end_time else None,
            "reason": exc.reason, "repeat_type": exc.repeat_type,
        }
        days[d]["exceptions"].append(entry)
        if exc.action == "remove":
            days[d]["has_remove"] = True
            remove_count += 1
        else:
            days[d]["has_add"] = True
            add_count += 1

    total = remove_count + add_count
    return ExceptionCalendarOut(
        year=year, month=month, days=days,
        summary={"total": total, "remove": remove_count, "add": add_count, "this_month": total},
    )


@router.post("/schedule/exceptions/batch")
def batch_import_exceptions(payload: ExceptionBatchImport, db: Session = Depends(get_db)):
    """批量导入例外。"""
    created = 0
    for item in payload.items:
        if item.action == "add" and item.course_id is not None:
            if not db.get(Course, item.course_id):
                continue
        exc = ScheduleException(**item.model_dump())
        db.add(exc)
        created += 1
    db.commit()
    return {"created": created, "total": len(payload.items)}


@router.get("/schedule/exceptions/expand")
def expand_repeat_exceptions(start: date, end: date, db: Session = Depends(get_db)):
    """展开重复例外为指定日期范围内的实际日期列表。"""
    exceptions = list(db.scalars(
        select(ScheduleException).where(ScheduleException.is_active.is_(True))
    ))
    result = []
    for exc in exceptions:
        dates = _expand_exception(exc, start, end)
        for d in dates:
            result.append({
                "exception_id": exc.id, "date": d.isoformat(), "action": exc.action,
                "course_name": _course_name(db, exc.course_id),
                "start_time": exc.start_time.strftime("%H:%M") if exc.start_time else None,
                "end_time": exc.end_time.strftime("%H:%M") if exc.end_time else None,
                "reason": exc.reason,
            })
    return {"total": len(result), "items": result}


def _expand_exception(exc: ScheduleException, start: date, end: date) -> list[date]:
    """展开单个重复例外。"""
    if exc.repeat_type == "none":
        return [exc.date] if start <= exc.date <= end else []

    config = json.loads(exc.repeat_config or "{}")
    dates = []
    current = max(start, exc.date)

    if exc.repeat_type == "daily":
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    elif exc.repeat_type == "weekly":
        weekdays = config.get("weekdays", [exc.date.weekday()])
        while current <= end:
            if current.weekday() in weekdays:
                dates.append(current)
            current += timedelta(days=1)
    elif exc.repeat_type == "biweekly":
        weekdays = config.get("weekdays", [exc.date.weekday()])
        week_offset = (exc.date - start).days // 7 % 2
        while current <= end:
            current_week = (current - start).days // 7
            if current.weekday() in weekdays and current_week % 2 == week_offset:
                dates.append(current)
            current += timedelta(days=1)
    elif exc.repeat_type == "monthly":
        month_days = config.get("month_days", [exc.date.day])
        while current <= end:
            if current.day in month_days:
                dates.append(current)
            current += timedelta(days=1)

    end_date = config.get("end_date")
    if end_date:
        end_date = date.fromisoformat(end_date)
        dates = [d for d in dates if d <= end_date]
    return dates


@router.delete("/schedule/exceptions/batch")
def batch_delete_exceptions(payload: ExceptionBatchDelete, db: Session = Depends(get_db)):
    deleted = 0
    for eid in payload.ids:
        exc = db.get(ScheduleException, eid)
        if exc:
            db.delete(exc)
            deleted += 1
    db.commit()
    return {"deleted": deleted}
