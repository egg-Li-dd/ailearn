"""选区内 AI 数据调整 / 从零生成端点。

Token 节俭设计：
1. 只发送选区行（每行压缩为关键字段，≈70 token）
2. 固定短 prompt 模板 + 字段白名单（AI 严格 JSON 动作，不解释）
3. 只回传变更字段（diff 而非整行重写）
4. 枚举/格式校验本地执行，不消耗 LLM

v2 优化：
- 字段校验统一走 core.validators（时间/日期/枚举/范围全覆盖）
- _fetch_before 改用批量 IN 查询（消除 N+1）
- generate 模式增加格式错误自动重试
- 关键路径全量日志
- JSON 提取增强（容忍多对象/数组/代码块）
- 内存限流保护（每分钟 20 次）
"""
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rate_limiter import ai_limiter
from ..core.simple_cache import ai_action_cache, ai_generate_cache, make_cache_key
from ..core.prompt_guard import scan as scan_prompt
from ..core.validators import (
    validate_action,
    validate_color,
    validate_course_id,
    validate_date,
    validate_difficulty,
    validate_is_active,
    validate_mastery,
    validate_sort,
    validate_time,
    validate_weekday,
)
from ..models import Course, KnowledgeNode, ScheduleException, ScheduleItem
from ..services.call_logger import set_function_type
from ..services.ai_gateway import AiGatewayError, chat_once, chat_once_with_usage

logger = logging.getLogger("ailearn.ai_action")
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

# ---------- 可配置参数（未来可移到 config.py） ----------
GENERATE_TEMPERATURE = 0.3
ACTION_TEMPERATURE = 0.15
RETRY_TEMPERATURE = 0.05
MAX_GENERATE_ITEMS = 15
MAX_ACTION_ITEMS = 30
RATE_LIMIT_PER_MINUTE = 20

# 每种上下文的字段白名单（仅这些字段允许 AI 修改）与展示字段
CONTEXT_SCHEMAS: dict[str, dict] = {
    "schedule_item": {
        "fields": ["weekday", "start_time", "end_time", "location", "is_active", "course_id"],
        "display": ["id", "weekday", "start_time", "end_time", "location"],
    },
    "course": {
        "fields": ["name", "subject_code", "color", "sort"],
        "display": ["id", "name", "subject_code", "color", "sort"],
    },
    "exception": {
        "fields": ["action", "course_id", "start_time", "end_time"],
        "display": ["id", "date", "action", "course_id", "start_time", "end_time"],
    },
    "knowledge_node": {
        "fields": ["name", "difficulty", "mastery", "summary"],
        "display": ["id", "name", "difficulty", "mastery"],
    },
}

FIELD_HINTS: dict[str, str] = {
    "weekday": "0=周一..6=周日",
    "action": "add=加课 remove=停课",
    "is_active": "true/false",
    "course_id": "科目ID",
    "difficulty": "1-5",
    "mastery": "0-100",
}

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 生成模式 schema：必填/可选字段与提示
GENERATE_SCHEMAS: dict[str, dict] = {
    "schedule_item": {
        "required": ["course_id", "weekday", "start_time", "end_time"],
        "optional": ["location"],
        "label": "课表项",
    },
    "course": {
        "required": ["name"],
        "optional": ["subject_code", "color", "sort"],
        "label": "科目",
    },
    "exception": {
        "required": ["date", "action"],
        "optional": ["course_id", "start_time", "end_time"],
        "label": "例外",
    },
}


class ActionRequest(BaseModel):
    context_type: str = Field(pattern="^(schedule_item|course|exception|knowledge_node)$")
    items: list[dict] = Field(min_length=1, max_length=MAX_ACTION_ITEMS)
    instruction: str = Field(min_length=2, max_length=500)


class GenerateRequest(BaseModel):
    context_type: str = Field(pattern="^(schedule_item|course|exception|knowledge_node)$")
    items: list[dict] = Field(default_factory=list)
    instruction: str = Field(min_length=2, max_length=500)


# ============================================================
# /ai/generate — 从零生成新行
# ============================================================

@router.post("/generate")
async def ai_generate(payload: GenerateRequest, request: Request, db: Session = Depends(get_db)):
    """自然语言 → 候选新行（不落库，前端预览后逐条创建）。"""
    # 限流
    client_key = request.client.host if request.client else "unknown"
    if not ai_limiter.allow(f"generate:{client_key}"):
        logger.warning("AI 生成限流触发: client=%s", client_key)
        raise HTTPException(status_code=429, detail="AI 生成请求过于频繁，请稍后再试")

    # Prompt 注入检测
    scan = scan_prompt(payload.instruction)
    if not scan.is_safe:
        logger.warning("AI 生成 Prompt 注入拦截: client=%s risk=%s patterns=%s",
                       client_key, scan.risk_level, scan.matched_patterns)
        raise HTTPException(status_code=400,
                            detail=f"检测到潜在 Prompt 注入（风险等级：{scan.risk_level}），请修改描述后重试")
    if scan.risk_level == "low":
        logger.info("AI 生成低风险 Prompt 标记: patterns=%s", scan.matched_patterns)

    schema = GENERATE_SCHEMAS.get(payload.context_type)
    if not schema:
        raise HTTPException(status_code=422, detail="该类型不支持 AI 生成")

    # 幂等性缓存：相同 context_type + instruction 短时间内返回相同结果
    cache_key = make_cache_key(payload.context_type, payload.instruction)
    cached = ai_generate_cache.get(cache_key)
    if cached is not None:
        logger.info("AI 生成缓存命中: type=%s", payload.context_type)
        return cached

    t0 = time.monotonic()

    # 科目映射（课表/例外生成时需要把课程名解析为 course_id）
    courses = list(db.scalars(select(Course).order_by(Course.sort, Course.id)))
    valid_course_ids = {c.id for c in courses}
    course_map_txt = (
        "\n".join(f"{c.id} = {c.name}" for c in courses)
        if courses else "（暂无科目，请先创建科目）"
    )
    required_hints = ", ".join(schema["required"])
    optional_hints = ", ".join(schema["optional"]) if schema["optional"] else "无"

    prompt = _build_generate_prompt(schema, required_hints, optional_hints, course_map_txt, payload.instruction)

    # LLM 调用（带格式校验重试）
    def _gen_validator(raw: str):
        data = json.loads(_extract_json(raw))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("缺少 items 数组")
        return items

    raw, items, usage = await _call_llm_with_retry(
        prompt, GENERATE_TEMPERATURE, context="generate", validator=_gen_validator
    )
    elapsed = time.monotonic() - t0
    usage_str = f" prompt={usage.get('prompt_tokens', '?')} completion={usage.get('completion_tokens', '?')} total={usage.get('total_tokens', '?')}" if usage else ""
    logger.info("AI 生成完成: type=%s elapsed=%.2fs raw_len=%d%s", payload.context_type, elapsed, len(raw), usage_str)

    # 逐条校验
    validated, ignored = _validate_generated_items(
        items, schema, payload.context_type, valid_course_ids,
        instruction=payload.instruction, courses=courses
    )

    if not validated:
        detail = "没能解析出有效的数据，请换一种描述方式"
        if ignored:
            detail += f"（已忽略 {len(ignored)} 条：{ignored[0]['reason']}）"
        logger.warning("AI 生成无有效结果: type=%s ignored=%d", payload.context_type, len(ignored))
        raise HTTPException(status_code=422, detail=detail)

    logger.info("AI 生成结果: type=%s valid=%d ignored=%d", payload.context_type, len(validated), len(ignored))
    result = {"items": validated, "count": len(validated), "ignored": ignored}
    ai_generate_cache.set(cache_key, result)
    return result


# ============================================================
# /ai/action — 调整选中行
# ============================================================

@router.post("/action")
async def ai_action(payload: ActionRequest, request: Request, db: Session = Depends(get_db)):
    """选中行 + 调整指令 → 动作 JSON + before/after 预览（不落库）。"""
    # 限流
    client_key = request.client.host if request.client else "unknown"
    if not ai_limiter.allow(f"action:{client_key}"):
        logger.warning("AI 调整限流触发: client=%s", client_key)
        raise HTTPException(status_code=429, detail="AI 调整请求过于频繁，请稍后再试")

    # Prompt 注入检测
    scan = scan_prompt(payload.instruction)
    if not scan.is_safe:
        logger.warning("AI 调整 Prompt 注入拦截: client=%s risk=%s patterns=%s",
                       client_key, scan.risk_level, scan.matched_patterns)
        raise HTTPException(status_code=400,
                            detail=f"检测到潜在 Prompt 注入（风险等级：{scan.risk_level}），请修改描述后重试")

    # 幂等性缓存：相同 context_type + instruction + 选中行ID集合
    selected_ids = ",".join(str(it.get("id", "")) for it in sorted(payload.items, key=lambda x: x.get("id", 0)))
    cache_key = make_cache_key(payload.context_type, payload.instruction, selected_ids)
    cached = ai_action_cache.get(cache_key)
    if cached is not None:
        logger.info("AI 调整缓存命中: type=%s", payload.context_type)
        return cached

    t0 = time.monotonic()
    compact = _compact_rows(payload.context_type, payload.items, db)
    prompt = _build_action_prompt(payload.context_type, compact, payload.instruction)

    # LLM 调用（带格式校验重试）
    def _action_validator(raw: str):
        return _validate_actions(payload.context_type, _extract_json(raw))

    raw, actions, usage = await _call_llm_with_retry(
        prompt, ACTION_TEMPERATURE, context="action", validator=_action_validator
    )
    elapsed = time.monotonic() - t0
    usage_str = f" prompt={usage.get('prompt_tokens', '?')} completion={usage.get('completion_tokens', '?')} total={usage.get('total_tokens', '?')}" if usage else ""
    logger.info("AI 调整完成: type=%s elapsed=%.2fs raw_len=%d%s", payload.context_type, elapsed, len(raw), usage_str)

    if not actions:
        logger.info("AI 调整无改动建议: type=%s", payload.context_type)
        return {"actions": [], "previews": [], "note": "没有改动建议"}

    # 批量取改动前的原始行（消除 N+1）
    before_map = _fetch_before_batch(payload.context_type, [a["id"] for a in actions], db)

    previews = []
    for a in actions:
        before = before_map.get(a["id"])
        if before is None:
            logger.warning("AI 调整引用了不存在的 id: %s", a["id"])
            continue
        previews.append(
            {
                "id": a["id"],
                "changes": [
                    {"field": k, "before": before.get(k), "after": v}
                    for k, v in a["fields"].items()
                ],
            }
        )

    logger.info("AI 调整结果: type=%s actions=%d previews=%d", payload.context_type, len(actions), len(previews))
    result = {"actions": actions, "previews": previews, "note": None}
    ai_action_cache.set(cache_key, result)
    return result


# ============================================================
# 内部函数
# ============================================================

def _build_generate_prompt(schema: dict, required_hints: str, optional_hints: str,
                            course_map_txt: str, instruction: str) -> str:
    return (
        f"你是 ai学 的数据生成助手。根据用户描述生成若干条新的{schema['label']}数据。\n"
        f'返回严格 JSON：{{"items":[{{...}}]}}，不要任何其他文字。\n'
        f"每条必须包含字段：{required_hints}；可选：{optional_hints}\n"
        f"规则：\n"
        f"- weekday 用 0-6 数字（0=周一）\n"
        f"- 时间用 HH:MM 24小时制\n"
        f"- course_id 必须取自已给出的科目映射，不要自造数字\n"
        f"- exception 的 action 用 add 或 remove\n"
        f"- course 的 color 必须是以下之一：--subj-ds, --subj-co, --subj-os, --subj-net, --subj-math, --subj-en, --subj-politics\n"
        f"- 不确定的数量按用户描述合理推断，最多 {MAX_GENERATE_ITEMS} 条\n"
        f"科目映射：\n{course_map_txt}\n\n"
        f"用户描述：{instruction}"
    )


def _build_action_prompt(context_type: str, compact: str, instruction: str) -> str:
    schema = CONTEXT_SCHEMAS[context_type]
    fields = ", ".join(
        f"{f}" + (f"({FIELD_HINTS[f]})" if f in FIELD_HINTS else "") for f in schema["fields"]
    )
    return (
        f"你是 ai学 的数据调整助手。用户选中了若干{context_type}数据行并对它们提出调整要求。\n"
        f'返回严格 JSON（不要任何其他文字）：{{"actions":[{{"id":数字id,"fields":{{改动字段}}}}]}}\n'
        f"规则：\n"
        f'- fields 只允许包含以下字段（按此约束输出）：{fields}\n'
        f"- 只输出需要改动的字段；不动的不写\n"
        f"- 不要解释、不要输出理由\n"
        f"- 若无需任何改动，返回 {{\"actions\":[]}}\n"
        f"- weekday 用 0-6 数字；is_active 用 true/false；时间用 HH:MM 24小时制\n\n"
        f"用户要求：{instruction}\n"
        f"选中数据：\n{compact}"
    )


async def _call_llm_with_retry(prompt: str, temperature: float, context: str,
                                 validator=None, max_retries: int = 1) -> tuple[str, object, dict]:
    """调用 LLM，可选格式校验失败时自动低权重重试。

    Args:
        prompt: 用户 prompt
        temperature: 首次调用温度
        context: 日志上下文标签
        validator: 可选校验函数 fn(raw) -> parsed_value，抛出 ValueError 时触发重试
        max_retries: 格式重试次数（默认1次）

    Returns:
        (raw_text, parsed_value, usage) — parsed_value 为 validator 的返回值，无 validator 时为 None；
        usage 为 token 用量统计 dict，服务商未返回时为空 dict。
    """
    system_msg = "你是严格遵循输出格式的数据生成助手。"
    raw = ""
    usage: dict = {}
    last_error: ValueError | None = None

    for attempt in range(max_retries + 1):
        try:
            set_function_type(context if context in ("generate", "action") else "generate")
            raw, usage = await chat_once_with_usage(
                [{"role": "system", "content": system_msg},
                 {"role": "user", "content": prompt}],
                temperature=temperature if attempt == 0 else RETRY_TEMPERATURE,
            )
        except AiGatewayError as e:
            logger.error("AI 调用失败 (%s, attempt %d): %s", context, attempt, e)
            raise HTTPException(status_code=400, detail=str(e)) from e

        if validator is None:
            return raw, None, usage

        try:
            parsed = validator(raw)
            return raw, parsed, usage
        except ValueError as e:
            last_error = e
            if attempt < max_retries:
                logger.warning("AI 格式校验失败 (%s, attempt %d)，低权重重试: %s",
                               context, attempt, e)
                system_msg = "只输出 JSON，不要代码块和任何解释。"
                continue
            logger.error("AI 格式校验最终失败 (%s): %s", context, e)

    raise HTTPException(status_code=422, detail=f"AI 返回格式无法解析：{last_error}")


def _extract_json(raw: str) -> str:
    """从 LLM 输出中提取 JSON（容忍代码块/前后杂质/多对象）。

    策略：
    1. 剥 markdown 代码块
    2. 找最外层匹配的 {}（用括号计数，避免字符串中的 } 干扰）
    3. 兜底：find('{') + rfind('}')
    """
    t = raw.strip()
    # 剥代码块
    if t.startswith("```"):
        parts = t.split("```", 2)
        if len(parts) >= 2:
            t = parts[1]
            if t.startswith("json"):
                t = t[4:]
            t = t.strip().strip("`").strip()
    # 括号计数找最外层匹配的 {}
    start = t.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(t)):
            ch = t[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return t[start:i + 1]
    # 兜底
    end = t.rfind("}")
    if start >= 0 and end > start:
        return t[start:end + 1]
    return t


def _validate_generated_items(items: list, schema: dict, context_type: str,
                               valid_course_ids: set[int],
                               instruction: str = "", courses: list = None) -> tuple[list, list]:
    """校验生成的条目，返回 (validated, ignored)。

    额外的 course_id 语义校验：当 instruction 中包含科目名时，
    检查 AI 输出的 course_id 对应的科目名是否在描述中出现，
    不匹配时添加 _semantic_warning 标记（不拒绝，仅警告）。
    """
    validated = []
    ignored = []
    all_fields = schema["required"] + schema["optional"]

    for it in items[:MAX_GENERATE_ITEMS]:
        if not isinstance(it, dict):
            ignored.append({"reason": "格式非对象"})
            continue

        # 必填校验
        missing = [f for f in schema["required"] if not it.get(f)]
        if missing:
            ignored.append({"reason": f"缺少必填字段: {', '.join(missing)}"})
            continue

        # 字段白名单过滤
        cleaned = {k: v for k, v in it.items() if k in all_fields}
        errors = []

        # 逐字段校验
        if "weekday" in cleaned:
            v, err = validate_weekday(cleaned["weekday"])
            if err:
                errors.append(err)
            else:
                cleaned["weekday"] = v

        if "course_id" in cleaned:
            v, err = validate_course_id(cleaned["course_id"], valid_course_ids)
            if err:
                errors.append(err)
            else:
                cleaned["course_id"] = v

        if "start_time" in cleaned:
            v, err = validate_time(cleaned["start_time"], "开始时间")
            if err:
                errors.append(err)
            else:
                cleaned["start_time"] = v

        if "end_time" in cleaned:
            v, err = validate_time(cleaned["end_time"], "结束时间")
            if err:
                errors.append(err)
            else:
                cleaned["end_time"] = v

        if "date" in cleaned:
            v, err = validate_date(cleaned["date"])
            if err:
                errors.append(err)
            else:
                cleaned["date"] = v

        if "action" in cleaned:
            v, err = validate_action(cleaned["action"])
            if err:
                errors.append(err)
            else:
                cleaned["action"] = v

        if "color" in cleaned:
            v, err = validate_color(cleaned["color"])
            if err:
                errors.append(err)
            else:
                cleaned["color"] = v

        if "sort" in cleaned:
            v, err = validate_sort(cleaned["sort"])
            if err:
                errors.append(err)
            else:
                cleaned["sort"] = v

        # 时间逻辑校验：开始必须早于结束
        if "start_time" in cleaned and "end_time" in cleaned and not errors:
            if cleaned["start_time"] >= cleaned["end_time"]:
                errors.append("开始时间必须早于结束时间")

        # course_id 语义校验：检查 AI 映射的科目是否在用户描述中出现
        if "course_id" in cleaned and not errors and instruction and courses:
            cid = cleaned["course_id"]
            course = next((c for c in courses if c.id == cid), None)
            if course:
                # 简单关键词匹配：科目名或其常见简称是否在描述中出现
                course_name = course.name.lower()
                instr_lower = instruction.lower()
                name_in_instr = course_name in instr_lower
                # 常见简称匹配（取科目名前2个字）
                short_name = course.name[:2].lower() if len(course.name) >= 2 else course_name.lower()
                short_in_instr = short_name in instr_lower and len(short_name) >= 2
                if not name_in_instr and not short_in_instr:
                    # 不直接拒绝，添加语义警告标记（前端可展示提示）
                    cleaned["_semantic_warning"] = f"科目「{course.name}」未在描述中明确提及，请注意确认"
                    logger.info("AI 生成 course_id 语义警告: cid=%d course=%s", cid, course.name)

        if errors:
            ignored.append({"reason": "; ".join(errors[:3])})
            continue

        validated.append(cleaned)

    return validated, ignored


def _validate_actions(context_type: str, raw: str) -> list[dict]:
    """解析并校验动作：字段白名单 + 值格式基本检查。"""
    schema = CONTEXT_SCHEMAS[context_type]
    allowed = set(schema["fields"])
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"AI 返回无法解析：{e}") from e
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        raise ValueError("AI 返回缺少 actions")

    cleaned = []
    for a in actions:
        if not isinstance(a, dict) or "id" not in a:
            continue
        fields = a.get("fields") or {}
        cleaned_fields = {k: v for k, v in fields.items() if k in allowed}

        # 逐字段校验
        if "weekday" in cleaned_fields:
            v, _ = validate_weekday(cleaned_fields["weekday"])
            if v is not None:
                cleaned_fields["weekday"] = v
            else:
                del cleaned_fields["weekday"]

        if "difficulty" in cleaned_fields:
            v, _ = validate_difficulty(cleaned_fields["difficulty"])
            if v is not None:
                cleaned_fields["difficulty"] = v

        if "mastery" in cleaned_fields:
            v, _ = validate_mastery(cleaned_fields["mastery"])
            if v is not None:
                cleaned_fields["mastery"] = v

        if "is_active" in cleaned_fields:
            v, _ = validate_is_active(cleaned_fields["is_active"])
            cleaned_fields["is_active"] = v

        if "start_time" in cleaned_fields:
            v, _ = validate_time(cleaned_fields["start_time"])
            if v is not None:
                cleaned_fields["start_time"] = v
            else:
                del cleaned_fields["start_time"]

        if "end_time" in cleaned_fields:
            v, _ = validate_time(cleaned_fields["end_time"])
            if v is not None:
                cleaned_fields["end_time"] = v
            else:
                del cleaned_fields["end_time"]

        if "color" in cleaned_fields:
            v, _ = validate_color(cleaned_fields["color"])
            if v is not None:
                cleaned_fields["color"] = v
            else:
                del cleaned_fields["color"]

        if "action" in cleaned_fields:
            v, _ = validate_action(cleaned_fields["action"])
            if v is not None:
                cleaned_fields["action"] = v
            else:
                del cleaned_fields["action"]

        if cleaned_fields:
            cleaned.append({"id": a["id"], "fields": cleaned_fields})
    return cleaned


def _compact_rows(context_type: str, items: list[dict], db: Session) -> str:
    """把选区行压成紧凑 JSON 文本（含人类可读映射，减少 AI 歧义）。"""
    schema = CONTEXT_SCHEMAS[context_type]
    out = []
    for it in items:
        row: dict = {"id": it.get("id")}
        for f in schema["display"]:
            if f == "id":
                continue
            v = it.get(f)
            if f == "weekday" and isinstance(v, int) and 0 <= v <= 6:
                row[f] = f"{v}({WEEKDAY_NAMES[v]})"
            elif f == "course_id" and v is not None:
                c = db.get(Course, v)
                row[f] = f"{v}({c.name if c else '?'})"
            else:
                row[f] = v
        out.append(row)
    return json.dumps(out, ensure_ascii=False)


def _fetch_before_batch(context_type: str, ids: list[int], db: Session) -> dict[int, dict]:
    """批量取改动前的原始行（消除 N+1 查询）。"""
    model = {
        "schedule_item": ScheduleItem,
        "course": Course,
        "exception": ScheduleException,
        "knowledge_node": KnowledgeNode,
    }[context_type]
    if not ids:
        return {}
    rows = db.scalars(select(model).where(model.id.in_(ids))).all()
    return {
        obj.id: {c.name: getattr(obj, c.name) for c in model.__table__.columns}
        for obj in rows
    }
