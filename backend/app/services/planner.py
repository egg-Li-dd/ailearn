"""规划 Agent：课前为学习会话生成任务清单（PRD D06 冻结）。

输入：科目（课程）、该科目掌握度最低 N 个节点、复习队列到期项
输出：3-8 张任务卡（JSON Schema 约束），type ∈ read/practice/memory/think/review
兜底：LLM 失败（未配置 key / 格式错 / 超时）→ 按科目默认任务模板生成，
      保证任务界面永远有内容，AI 只是增强不是依赖。

调用方：
- 管理台：POST /api/v1/sessions/{id}/plan（人工触发）
- 调度器：会话进入 PRE_CLASS 且无任务时自动触发
"""
import asyncio
import json
import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Course, KnowledgeNode, ReviewQueue, StudySession, Task
from ..models.enums import ReviewStatus, TaskStatus, TaskType
import time

from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_once
from . import experiment_service

logger = logging.getLogger("ailearn.planner")

TASK_TYPES = (TaskType.READ, TaskType.PRACTICE, TaskType.MEMORY, TaskType.THINK, TaskType.REVIEW)
WEAK_N = 5  # 薄弱节点取数
TASK_RANGE = (3, 8)  # 任务卡数量范围


# ---------- 输入提取 ----------


def _weak_nodes(db: Session, course_id: int, limit: int = WEAK_N) -> list[KnowledgeNode]:
    """该科目未掌握知识点：优先 learning（学习中）再 untouched（未开始），各按 mastery 升序。

    未掌握定义：status=learning 或 status=untouched（level>=3）。
    mastered（mastery>=80）和 review（到期复习）不进入此队列。
    """
    learning = list(
        db.scalars(
            select(KnowledgeNode)
            .where(
                KnowledgeNode.subject_id == course_id,
                KnowledgeNode.level >= 3,
                KnowledgeNode.status == "learning",
            )
            .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
        )
    )
    untouched = list(
        db.scalars(
            select(KnowledgeNode)
            .where(
                KnowledgeNode.subject_id == course_id,
                KnowledgeNode.level >= 3,
                KnowledgeNode.status == "untouched",
            )
            .order_by(KnowledgeNode.mastery, KnowledgeNode.id)
        )
    )
    combined = learning + untouched
    return combined[:limit]


def _unmastered_count(db: Session, course_id: int) -> int:
    """该科目未掌握知识点总数（learning + untouched，level>=3）。"""
    return db.scalar(
        select(func.count(KnowledgeNode.id))
        .where(
            KnowledgeNode.subject_id == course_id,
            KnowledgeNode.level >= 3,
            KnowledgeNode.status.in_(["learning", "untouched"]),
        )
    ) or 0


def _remaining_sessions(db: Session, course_id: int, end_date: date) -> int:
    """计算从今天到 end_date（含）之间，该科目的实际上课次数。

    考虑：
    - 周课表 ScheduleItem（weekday 匹配且 is_active）
    - 日期例外 ScheduleException：action=remove 排除，action=add 增加
    - 只统计未来日期（今天及以后）
    """
    from datetime import timedelta as _td
    from ..models.course import ScheduleItem, ScheduleException

    today = date.today()
    if end_date < today:
        return 0

    # 加载该科目的周课表项
    week_items = list(db.scalars(
        select(ScheduleItem).where(
            ScheduleItem.course_id == course_id,
            ScheduleItem.is_active.is_(True),
        )
    ))
    weekdays = {item.weekday for item in week_items}

    # 加载日期例外（从今天到 end_date）
    exceptions = list(db.scalars(
        select(ScheduleException).where(
            ScheduleException.date >= today,
            ScheduleException.date <= end_date,
            ScheduleException.is_active.is_(True),
        )
    ))
    remove_dates = set()
    add_dates = set()
    for exc in exceptions:
        if exc.action == "remove" and (exc.course_id is None or exc.course_id == course_id):
            remove_dates.add(exc.date)
        elif exc.action == "add" and exc.course_id == course_id:
            add_dates.add(exc.date)

    # 遍历每一天统计
    count = 0
    d = today
    while d <= end_date:
        # 全天停课（course_id=None 的 remove）
        if d in remove_dates and any(e.date == d and e.course_id is None for e in exceptions):
            d += _td(days=1)
            continue
        # 该科目当天停课
        if d in remove_dates:
            d += _td(days=1)
            continue
        # 周课表有课 或 加课例外
        if d.weekday() in weekdays or d in add_dates:
            count += 1
        d += _td(days=1)

    return count


def _calc_completion_rate(db: Session, course_id: int, recent_n: int = 5) -> float | None:
    """计算该科目最近 N 次课的平均任务完成率。

    完成率 = done任务数 / (总任务数 - skipped任务数)
    仅统计已结束的会话（status=done 或 overdue）。
    数据不足时返回 None（不调整）。
    """
    from ..models import StudySession, Task

    # 查询最近 N 个已结束的会话
    sessions = list(db.scalars(
        select(StudySession)
        .where(
            StudySession.course_id == course_id,
            StudySession.status.in_(["done", "overdue"]),
        )
        .order_by(StudySession.date.desc())
        .limit(recent_n)
    ))
    if not sessions:
        return None

    total_done = 0
    total_effective = 0
    for s in sessions:
        tasks = list(db.scalars(
            select(Task).where(Task.session_id == s.id)
        ))
        if not tasks:
            continue
        done = sum(1 for t in tasks if t.status == "done")
        skipped = sum(1 for t in tasks if t.status == "skipped")
        effective = len(tasks) - skipped
        if effective > 0:
            total_done += done
            total_effective += effective

    if total_effective == 0:
        return None
    return total_done / total_effective


def _adjust_daily_target(daily_target: int, completion_rate: float | None) -> int:
    """根据历史完成率动态调整 daily_target。

    - 完成率 < 0.7 → 减少 20%（任务太多，做不完）
    - 完成率 > 0.9 → 增加 20%（任务太少，吃不饱）
    - 其他 → 不变
    - 限制调整范围：不超过原始值的 ±50%
    """
    if completion_rate is None or daily_target <= 0:
        return daily_target

    if completion_rate < 0.7:
        adjusted = int(daily_target * 0.8)
    elif completion_rate > 0.9:
        adjusted = int(daily_target * 1.2)
    else:
        adjusted = daily_target

    # 限制调整范围
    lower = max(1, int(daily_target * 0.5))
    upper = int(daily_target * 1.5)
    return max(lower, min(upper, adjusted))


def _get_carryover_tasks(db: Session, course_id: int, current_session_id: int) -> list[dict]:
    """获取上一次课未完成的任务（用于滚动到本次课）。

    规则：
    - 找该科目最近一个已结束的会话（status=done/overdue，且不是当前会话）
    - 筛选 status != done 且 status != skipped 的任务
    - 返回复制后的任务字典（保留学习进度）
    """
    from ..models import StudySession, Task

    # 查询最近一个已结束的会话（排除当前会话）
    prev_session = db.scalar(
        select(StudySession)
        .where(
            StudySession.course_id == course_id,
            StudySession.id != current_session_id,
            StudySession.status.in_(["done", "overdue"]),
        )
        .order_by(StudySession.date.desc())
        .limit(1)
    )
    if prev_session is None:
        return []

    # 查询未完成的任务
    unfinished = list(db.scalars(
        select(Task).where(
            Task.session_id == prev_session.id,
            Task.status.notin_(["done", "skipped"]),
        )
    ))
    if not unfinished:
        return []

    # 转换为字典（保留学习进度）
    carryover = []
    for t in unfinished:
        carryover.append({
            "type": t.type,
            "title": f"[延续] {t.title}",
            "minutes": t.est_minutes or 15,
            "node_id": t.target_knowledge_id,
            "carryover": True,
            "completion": t.completion,
            "best_score": t.best_score,
            "score_history": t.score_history,
        })
    return carryover


def _due_reviews(db: Session, course_id: int) -> list[tuple[ReviewQueue, KnowledgeNode]]:
    """该科目到期未完成的复习项（今天以内到期都算，供任务置顶复习）。

    返回 (ReviewQueue, KnowledgeNode) 元组列表，已 join 节点名与掌握度，
    避免 prompt 拼装时反复回查。
    """
    from datetime import date, datetime, time

    end_of_day = datetime.combine(date.today(), time.max)
    rows = db.execute(
        select(ReviewQueue, KnowledgeNode)
        .join(KnowledgeNode, ReviewQueue.node_id == KnowledgeNode.id)
        .where(
            KnowledgeNode.subject_id == course_id,
            ReviewQueue.status == ReviewStatus.OPEN,
            ReviewQueue.due_at <= end_of_day,
        )
        .order_by(ReviewQueue.due_at)
    ).all()
    return [(r, n) for r, n in rows]


# ---------- LLM 生成 ----------



def _build_planner_messages_v1(
    course: Course,
    weak: list[KnowledgeNode],
    due: list[tuple[ReviewQueue, KnowledgeNode]],
    days_remaining: int | None = None,
    daily_target: int | None = None,
    unmastered_total: int = 0,
) -> list[dict]:
    """旧版 v1：单 user + 完整 JSON 示例（A/B 对照组）。

    与 v2（_build_planner_messages）对比：
    - v1: 单 user 消息，角色+参数+完整JSON示例+要求全部混在一起
    - v2: system+user 分离，字段定义表代替完整示例，预计节省 token 40%
    """
    weak_text = "、".join(f"「{n.name}」(id={n.id})" for n in weak) or "（暂无薄弱记录）"
    due_text = (
        "、".join(f"「{n.name}」(id={r.node_id},掌握度{n.mastery})" for r, n in due[:3])
        if due else "（无）"
    )
    goal_line = ""
    if days_remaining is not None and daily_target is not None:
        goal_line = (
            f"学习目标：剩余 {days_remaining} 天，未掌握知识点共 {unmastered_total} 个，"
            f"每日需攻克约 {daily_target} 个。任务量要匹配每日目标，优先安排学习中的知识点。\n"
        )
    prompt = (
        f"你是 ai学 的规划教练。为一个考研学习会话生成课前/课中任务清单。\n"
        f"科目：{course.name}\n"
        f"{goal_line}"
        f"该科目薄弱知识点（优先安排练习/思考，已按学习中→未开始排序）：{weak_text}\n"
        f"到期复习项（每个到期项对应一张 type=review 的卡，必须放最前面）：{due_text}\n"
        f'返回严格 JSON（不要任何其他文字）：{{"tasks":['
        f'{{"type":"read|practice|memory|think|review","title":"简短可执行的任务名(<=30字)",'
        f'"minutes":预计分钟数(int),"node_id":知识点id(int,review类型必须填对应到期项的id,其他类型可选)}},...]}}\n'
        f"要求：3-8 张；类型多样不全是同一类；title 可执行不带编号；"
        f"每个到期复习项必须单独生成一张 type=review 卡且 node_id 正确对应，review 卡不超过 3 张；"
        f"薄弱点如果存在至少安排一张 practice 或 think；"
        f"若设置了每日目标，任务卡总知识点覆盖量应接近 daily_target。"
    )
    return [{"role": "user", "content": prompt}]


def _build_planner_messages(
    course: Course,
    weak: list[KnowledgeNode],
    due: list[tuple[ReviewQueue, KnowledgeNode]],
    days_remaining: int | None = None,
    daily_target: int | None = None,
    unmastered_total: int = 0,
) -> list[dict]:
    """构建规划任务生成的 messages（system+user 分离 + 字段定义表）。

    优化策略（对照 prompt-optimization-demo 验证方案）：
    - system: 角色 + 字段定义表（代替完整JSON示例） + 合并规则段
    - user: 仅参数 JSON（科目/薄弱点/到期复习/学习目标）
    - 预计节省 prompt token 约 40%
    """
    system_content = (
        "你是 ai学 的规划教练。为考研学习会话生成课前/课中任务清单。\n"
        "输出严格 JSON，不要任何其他文字。\n\n"
        "字段定义：\n"
        "- tasks: array 任务卡列表（3-8张）\n"
        "- type: enum(read|practice|memory|think|review) 任务类型\n"
        "- title: string 任务名(<=30字，可执行不带编号)\n"
        "- minutes: int 预计分钟数\n"
        "- node_id: int 知识点id（review类型必填对应到期项id，其他类型可选）\n\n"
        "规则：\n"
        "- 类型多样，不全是同一类\n"
        "- 每个到期复习项单独生成一张 type=review 卡，放最前面，review 卡不超过3张\n"
        "- 薄弱点如果存在，至少安排一张 practice 或 think\n"
        "- 若设置了每日目标，任务卡总知识点覆盖量应接近 daily_target"
    )

    weak_list = [{"id": n.id, "name": n.name, "mastery": n.mastery} for n in weak]
    due_list = [{"id": r.node_id, "name": n.name, "mastery": n.mastery} for r, n in due[:3]]

    user_data: dict = {
        "course": course.name,
        "weak_nodes": weak_list,
        "due_reviews": due_list,
    }
    if days_remaining is not None and daily_target is not None:
        user_data["goal"] = {
            "days_remaining": days_remaining,
            "unmastered_total": unmastered_total,
            "daily_target": daily_target,
        }

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_data, ensure_ascii=False)},
    ]


def _parse_tasks(raw: str) -> list[dict] | None:
    """解析并校验 LLM 输出；不满足约束返回 None（走模板兜底）。"""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    tasks = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(tasks, list) or not tasks:
        return None
    out: list[dict] = []
    for t in tasks[: TASK_RANGE[1]]:
        if not isinstance(t, dict):
            continue
        typ = t.get("type")
        if typ not in TASK_TYPES:
            continue
        title = str(t.get("title", "")).strip()
        if not title or len(title) > 60:
            continue
        try:
            minutes = int(t.get("minutes") or 10)
        except (TypeError, ValueError):
            minutes = 10
        # node_id 校验：合法正整数保留，不合法降级为 None（不丢弃卡片）
        node_id = t.get("node_id")
        if node_id is not None:
            try:
                node_id = int(node_id)
                if node_id <= 0:
                    node_id = None
            except (TypeError, ValueError):
                node_id = None
        out.append({
            "type": typ, "title": title,
            "minutes": max(5, min(120, minutes)),
            "node_id": node_id,
        })
    if not (TASK_RANGE[0] <= len(out) <= TASK_RANGE[1]):
        return None
    return out


async def _llm_tasks(
    db: Session,
    course: Course,
    weak: list[KnowledgeNode],
    due: list[tuple[ReviewQueue, KnowledgeNode]],
    days_remaining: int | None = None,
    daily_target: int | None = None,
    unmastered_total: int = 0,
) -> list[dict] | None:
    """调用 LLM 生成任务卡；任何失败返回 None（调用方兜底）。

    A/B 实验：planner_prompt_v2
    - control: v1 旧版（单 user + 完整 JSON 示例）
    - treatment: v2 优化版（system+user + 字段定义表）
    """
    # A/B 实验分桶
    _exp = experiment_service.get_experiment(db, "planner_prompt_v2")
    _variant = experiment_service.assign_variant(_exp, f"course_{course.id}") if _exp else None
    _exp_start = time.monotonic()

    if _variant == "control":
        messages = _build_planner_messages_v1(course, weak, due, days_remaining, daily_target, unmastered_total)
    else:
        messages = _build_planner_messages(course, weak, due, days_remaining, daily_target, unmastered_total)

    try:
        set_function_type("planner")
        raw = await chat_once(messages, temperature=0.5)
    except AiGatewayError as e:
        logger.warning("planner LLM 失败（走模板兜底）：%s", e)
        if _exp and _variant:
            _exp_duration = int((time.monotonic() - _exp_start) * 1000)
            experiment_service.record_event(_exp, _variant, f"course_{course.id}", "planner", {
                "format_valid": False,
                "duration_ms": _exp_duration,
            })
        return None
    tasks = _parse_tasks(raw)
    if tasks is None:
        logger.warning("planner LLM 输出格式异常（走模板兜底）：%.200s", raw)

    # 记录实验事件
    if _exp and _variant:
        _exp_duration = int((time.monotonic() - _exp_start) * 1000)
        experiment_service.record_event(_exp, _variant, f"course_{course.id}", "planner", {
            "format_valid": tasks is not None,
            "duration_ms": _exp_duration,
        })

    return tasks


# ---------- 模板兜底 ----------


def _template_tasks(
    course: Course,
    weak: list[KnowledgeNode],
    due: list[tuple[ReviewQueue, KnowledgeNode]],
    daily_target: int | None = None,
) -> list[dict]:
    """科目默认任务模板：无论 AI 可用与否都保证任务清单非空。

    到期复习项最多生成 3 张 review 卡（每张对应一个到期知识点），置顶排列。
    若设置了 daily_target，练习卡数量会匹配目标知识点数。
    """
    tasks: list[dict] = []
    # 1. 到期复习（每个到期项一张卡，最多 3 张）
    for r, n in due[:3]:
        tasks.append(
            {
                "type": TaskType.REVIEW,
                "title": f"复习「{n.name}」（掌握度 {n.mastery}）",
                "minutes": 15,
                "node_id": r.node_id,
            }
        )
    # 2. 预习
    tasks.append(
        {
            "type": TaskType.READ,
            "title": f"通读《{course.name}》本节课对应章节，标出不懂处",
            "minutes": 10,
        }
    )
    # 3. 薄弱点练习（根据 daily_target 调整数量）
    practice_count = 1
    if daily_target is not None and daily_target > 0:
        # 复习卡已占用的知识点数
        review_node_count = min(len(due), 3)
        # 还需要覆盖的知识点数
        remaining = max(1, daily_target - review_node_count)
        practice_count = min(remaining, len(weak), 5)  # 最多5张练习卡

    for i in range(practice_count):
        if i < len(weak):
            node = weak[i]
            tasks.append(
                {
                    "type": TaskType.PRACTICE,
                    "title": f"练习薄弱点「{node.name}」相关题目 2-3 道",
                    "minutes": 15,
                    "node_id": node.id,
                }
            )
        else:
            tasks.append(
                {
                    "type": TaskType.PRACTICE,
                    "title": f"挑 2-3 道《{course.name}》章节例题先做一遍",
                    "minutes": 15,
                }
            )
    # 4. 思考/带着问题听课
    think_node = weak[practice_count] if len(weak) > practice_count else None
    if think_node:
        tasks.append(
            {
                "type": TaskType.THINK,
                "title": f"上课留意薄弱点「{think_node.name}」的讲解",
                "minutes": 10,
                "node_id": think_node.id,
            }
        )
    else:
        tasks.append(
            {
                "type": TaskType.THINK,
                "title": f"带着 1 个问题去听《{course.name}」，下课后自答",
                "minutes": 10,
            }
        )
    # 5. 记忆/总结
    tasks.append(
        {
            "type": TaskType.MEMORY,
            "title": f"课后回顾本节核心概念/公式并默写一遍",
            "minutes": 10,
        }
    )
    # 限制总数在 3-8 之间
    return tasks[:TASK_RANGE[1]]


def _enforce_daily_target(
    cards: list[dict],
    weak: list[KnowledgeNode],
    daily_target: int | None,
) -> list[dict]:
    """后处理：强制约束任务卡的知识点覆盖量接近 daily_target。

    - 统计已绑定 node_id 的任务数（不含 review）
    - 不足时从薄弱节点补充 practice 卡
    - 超出过多（>daily_target+2）时截断多余的非 review 卡
    """
    if daily_target is None or daily_target <= 0:
        return cards

    # 已绑定知识点的任务（review 也算覆盖）
    node_bound = [c for c in cards if c.get("node_id") is not None]
    review_count = sum(1 for c in cards if c["type"] == TaskType.REVIEW)
    current_coverage = len(node_bound)

    # 不足：补充 practice 卡
    if current_coverage < daily_target:
        needed = daily_target - current_coverage
        # 找出 weak 中还没被使用的节点
        used_ids = {c["node_id"] for c in node_bound if c.get("node_id")}
        available = [n for n in weak if n.id not in used_ids]
        for i in range(min(needed, len(available))):
            node = available[i]
            # 插入到 review 卡之后、memory 卡之前
            insert_idx = review_count + 1  # review 之后，read 之后
            cards.insert(
                min(insert_idx, len(cards)),
                {
                    "type": TaskType.PRACTICE,
                    "title": f"练习薄弱点「{node.name}」相关题目 2-3 道",
                    "minutes": 15,
                    "node_id": node.id,
                }
            )
    # 超出过多：截断多余的非 review 卡
    elif current_coverage > daily_target + 2:
        # 保留 review 卡，删除多余的 practice/think 卡
        keep = []
        node_count = 0
        for c in cards:
            if c["type"] == TaskType.REVIEW:
                keep.append(c)
                node_count += 1
            elif c.get("node_id") and node_count < daily_target + 2:
                keep.append(c)
                node_count += 1
            elif not c.get("node_id"):
                keep.append(c)  # 无 node_id 的卡（read/memory）保留
        cards = keep

    # 最终限制在 3-8 张
    return cards[:TASK_RANGE[1]]


# ---------- 主入口 ----------


async def plan_session(db: Session, session: StudySession) -> list[Task]:
    """为会话生成任务清单并落库（幂等：已有任务直接返回）。"""
    existing = list(
        db.scalars(select(Task).where(Task.session_id == session.id).order_by(Task.seq))
    )
    if existing:
        return existing

    course = db.get(Course, session.course_id)
    if course is None:
        course = Course(name=f"科目#{session.course_id}")
    weak = _weak_nodes(db, session.course_id)
    due = _due_reviews(db, session.course_id)

    # === 学习目标：未掌握总数 / 剩余上课次数 = 每次目标 ===
    import math
    from datetime import timedelta as _td
    unmastered_total = _unmastered_count(db, session.course_id)
    sessions_remaining = None
    daily_target = None
    if course.target_days is not None and course.goal_start_date is not None:
        # 目标结束日期 = 开始日期 + target_days
        goal_end_date = course.goal_start_date + _td(days=course.target_days)
        sessions_remaining = _remaining_sessions(db, session.course_id, goal_end_date)
        if sessions_remaining > 0:
            daily_target = max(1, math.ceil(unmastered_total / sessions_remaining))
    # 兼容旧字段名（LLM prompt 中仍用 days_remaining 表示剩余次数）
    days_remaining = sessions_remaining

    # === P2：根据历史完成率动态调整 ===
    completion_rate = _calc_completion_rate(db, session.course_id)
    if completion_rate is not None and daily_target is not None:
        original_target = daily_target
        daily_target = _adjust_daily_target(daily_target, completion_rate)
        logger.info(
            "course %d daily_target adjusted: %d -> %d (completion_rate=%.2f)",
            session.course_id, original_target, daily_target, completion_rate,
        )

    # === P3：获取上节课未完成的延续任务 ===
    carryover = _get_carryover_tasks(db, session.course_id, session.id)
    carryover_node_count = sum(1 for c in carryover if c.get("node_id"))
    # 扣除延续任务占用的知识点数
    effective_target = None
    if daily_target is not None:
        effective_target = max(0, daily_target - carryover_node_count)

    # 仅当配置了 AI Key 才尝试 LLM（未配置直接模板，不打无谓日志）
    from ..core.ai_config import read_ai_config

    cfg = read_ai_config(db)
    cards: list[dict] | None = None
    if cfg.get("api_key"):
        cards = await _llm_tasks(
            db, course, weak, due,
            days_remaining=days_remaining,
            daily_target=daily_target,
            unmastered_total=unmastered_total,
        )
    # 模板兜底（适配 effective_target，扣除延续任务）
    if cards is None:
        tasks = _template_tasks(course, weak, due, daily_target=effective_target)
    else:
        # 后处理：强制约束任务量接近 effective_target
        tasks = _enforce_daily_target(cards, weak, effective_target)

    # P3：合并延续任务（放在最前面）
    if carryover:
        tasks = carryover + tasks
        logger.info("course %d carryover tasks: %d", session.course_id, len(carryover))

    seq = 0
    for c in tasks:
        seq += 1
        task = Task(
            session_id=session.id,
            seq=seq,
            type=c["type"],
            title=c["title"],
            est_minutes=c.get("minutes"),
            target_knowledge_id=c.get("node_id"),
            status=TaskStatus.TODO,
        )
        # P3：延续任务保留学习进度
        if c.get("carryover"):
            task.completion = c.get("completion", 0)
            task.best_score = c.get("best_score")
            task.score_history = c.get("score_history")
        db.add(task)
    db.commit()
    logger.info(
        "plan session %d -> %d tasks (llm=%s, target=%s, effective=%s, carryover=%d, rate=%.2f, unmastered=%d)",
        session.id, len(tasks), cards is not None, daily_target, effective_target,
        len(carryover), completion_rate or 0, unmastered_total,
    )
    return list(
        db.scalars(select(Task).where(Task.session_id == session.id).order_by(Task.seq))
    )


async def plan_today_pending(db: Session) -> list[dict]:
    """为今天所有 SATISFY 条件（PRE_CLASS/IN_CLASS 且无任务）的会话补生成任务。

    供调度器在 tick 时顺带调用：保证进入课前即有任务清单。
    """
    from sqlalchemy import select as _select

    sessions = list(
        db.scalars(
            _select(StudySession).where(
                StudySession.status.in_(["pre_class", "in_class"])
            )
        )
    )
    results: list[dict] = []
    for s in sessions:
        has_tasks = (
            db.scalar(
                _select(Task.id).where(Task.session_id == s.id).limit(1)
            )
            is not None
        )
        if has_tasks:
            continue
        tasks = await plan_session(db, s)
        results.append({"session_id": s.id, "tasks": [t.id for t in tasks]})
    return results
