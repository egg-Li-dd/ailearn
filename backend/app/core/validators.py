"""AI 生成/调整结果的字段校验工具。

所有校验函数返回 (cleaned_value, error_message_or_None)。
校验不通过时返回 None + 错误原因，调用方决定忽略或报错。
"""
import re
from datetime import datetime

# 预定义科目颜色白名单（与前端 COURSE_COLORS 保持一致）
VALID_COLORS = {
    "--subj-ds", "--subj-co", "--subj-os", "--subj-net",
    "--subj-math", "--subj-en", "--subj-politics",
}

VALID_ACTIONS = {"add", "remove"}

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]?\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_weekday(value) -> tuple[int | None, str | None]:
    """weekday: 0-6 整数。"""
    try:
        wd = int(value)
    except (TypeError, ValueError):
        return None, "weekday 非数字"
    if not 0 <= wd <= 6:
        return None, f"weekday 超出范围 0-6: {wd}"
    return wd, None


def validate_time(value, field: str = "时间") -> tuple[str | None, str | None]:
    """HH:MM 24小时制，容忍 9:00 → 09:00。"""
    if not isinstance(value, str):
        return None, f"{field} 非字符串"
    m = TIME_RE.match(value.strip())
    if not m:
        return None, f"{field} 格式应为 HH:MM: {value}"
    hour, minute = int(m.group(1)), int(m.group(2))
    return f"{hour:02d}:{minute:02d}", None


def validate_date(value) -> tuple[str | None, str | None]:
    """YYYY-MM-DD 格式。"""
    if not isinstance(value, str):
        return None, "日期非字符串"
    v = value.strip()
    if not DATE_RE.match(v):
        return None, f"日期格式应为 YYYY-MM-DD: {value}"
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None, f"日期无效: {value}"
    return v, None


def validate_color(value) -> tuple[str | None, str | None]:
    """科目颜色必须在预定义白名单中。"""
    if not isinstance(value, str) or value not in VALID_COLORS:
        return None, f"颜色不在允许列表中: {value}"
    return value, None


def validate_action(value) -> tuple[str | None, str | None]:
    """例外动作必须是 add 或 remove。"""
    if not isinstance(value, str) or value not in VALID_ACTIONS:
        return None, f"动作应为 add 或 remove: {value}"
    return value, None


def validate_sort(value) -> tuple[int | None, str | None]:
    """排序号：非负整数。"""
    try:
        s = int(value)
    except (TypeError, ValueError):
        return None, f"排序号非数字: {value}"
    if s < 0:
        return None, f"排序号不能为负: {s}"
    return s, None


def validate_difficulty(value) -> tuple[int | None, str | None]:
    """难度：1-5 整数。"""
    try:
        d = int(value)
    except (TypeError, ValueError):
        return None, f"难度非数字: {value}"
    return max(1, min(5, d)), None


def validate_mastery(value) -> tuple[int | None, str | None]:
    """掌握度：0-100 整数。"""
    try:
        m = int(value)
    except (TypeError, ValueError):
        return None, f"掌握度非数字: {value}"
    return max(0, min(100, m)), None


def validate_course_id(value, valid_ids: set[int]) -> tuple[int | None, str | None]:
    """科目 ID：必须为数字且在现有科目集合中。"""
    try:
        cid = int(value)
    except (TypeError, ValueError):
        return None, f"course_id 非数字: {value}"
    if cid not in valid_ids:
        return None, f"科目ID {cid} 不在现有科目中，请先在科目管理创建"
    return cid, None


def validate_is_active(value) -> tuple[bool, str | None]:
    """is_active：布尔值，容忍字符串 'true'/'false'。"""
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str):
        if value.lower() == "true":
            return True, None
        if value.lower() == "false":
            return False, None
    return bool(value), None
