"""Prompt 注入防护：检测用户输入中的注入尝试。

策略：
1. 关键词黑名单检测（中英文）
2. 系统提示词泄露诱导检测
3. 角色越权诱导检测
4. 返回 (is_safe, risk_level, matched_patterns)

注意：这是轻量级防护，不能替代系统消息强化和输出校验。
对于教育场景，误报代价高于漏报，因此采用保守阈值。
"""
import re
from dataclasses import dataclass, field


@dataclass
class ScanResult:
    is_safe: bool
    risk_level: str  # "none" | "low" | "medium" | "high"
    matched_patterns: list[str] = field(default_factory=list)
    sanitized: str = ""  # 清理后的文本（仅移除明显注入指令）


# 高风险：明确要求忽略/覆盖系统指令
HIGH_RISK_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior|above|all)\s*(instructions?|prompts?|rules?)", "ignore_previous_instructions"),
    (r"disregard\s+(all\s+)?(previous|prior|above|all)\s*(instructions?|prompts?|rules?)", "disregard_previous"),
    (r"忽略(之前|前面|以上|先前)?(的)?(所有|全部|任何)?(的)?(指令|提示|规则|系统提示|设定)", "ignore_previous_cn"),
    (r"忘掉(之前|前面|以上)?(的)?(所有|全部)?(的)?(指令|提示|规则|设定)", "forget_previous_cn"),
    (r"你现在是|从现在开始你是|your\s+are\s+now|you\s+are\s+now", "role_hijack"),
    (r"扮演|假装是|act\s+as|pretend\s+to\s+be", "role_pretend"),
    (r"system\s+prompt|系统提示词|系统提示", "system_prompt_leak"),
    (r"reveal\s+(your\s+)?(system\s+)?prompt|泄露|输出(你的)?(系统)?提示(词)?", "reveal_prompt"),
    (r"jailbreak|越狱|绕过(安全|限制|防护|验证|检查)", "jailbreak_attempt"),
    (r"developer\s+mode|开发者模式|god\s+mode|上帝模式", "mode_override"),
]

# 中风险：可能是注入也可能是正常描述，需要结合上下文
MEDIUM_RISK_PATTERNS = [
    (r"do\s+not\s+follow|不要(遵守|遵循|按照|理会|管)", "do_not_follow"),
    (r"override|覆盖(所有|全部|任何)?(的)?(指令|规则|设置|限制|安全)", "override_attempt"),
    (r"bypass|跳过(验证|检查|安全|限制|防护)", "bypass_attempt"),
    (r"new\s+instructions?|新的指令|新指令", "new_instructions"),
    (r"always\s+comply|必须(无条件|始终|永远)(服从|遵守|执行|答应)", "always_comply"),
]


def scan(text: str) -> ScanResult:
    """扫描用户输入，返回检测结果。

    教育场景采用保守策略：
    - 高风险模式命中 → risk_level=high，is_safe=False
    - 中风险模式命中 ≥2 个 → risk_level=medium，is_safe=False
    - 中风险模式命中 1 个 → risk_level=low，is_safe=True（仅警告）
    - 无命中 → risk_level=none，is_safe=True
    """
    if not text:
        return ScanResult(is_safe=True, risk_level="none", sanitized=text)

    text_lower = text.lower()
    high_matches = []
    medium_matches = []

    for pattern, name in HIGH_RISK_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            high_matches.append(name)

    for pattern, name in MEDIUM_RISK_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            medium_matches.append(name)

    all_matches = high_matches + medium_matches

    if high_matches:
        return ScanResult(
            is_safe=False,
            risk_level="high",
            matched_patterns=all_matches,
            sanitized=_sanitize(text, high_matches),
        )

    if len(medium_matches) >= 2:
        return ScanResult(
            is_safe=False,
            risk_level="medium",
            matched_patterns=all_matches,
            sanitized=_sanitize(text, medium_matches),
        )

    if len(medium_matches) == 1:
        return ScanResult(
            is_safe=True,  # 低风险放行，仅记录
            risk_level="low",
            matched_patterns=all_matches,
            sanitized=text,
        )

    return ScanResult(is_safe=True, risk_level="none", sanitized=text)


def _sanitize(text: str, matched_names: list[str]) -> str:
    """轻量清理：移除明显的注入指令行，保留正常描述内容。

    策略：按行分割，删除包含高风险关键词的行。
    如果删除后文本为空，返回原始文本（让下游校验处理）。
    """
    lines = text.split("\n")
    # 构建需要删除的关键词集合
    kill_keywords = []
    for pattern, name in HIGH_RISK_PATTERNS + MEDIUM_RISK_PATTERNS:
        if name in matched_names:
            # 从正则中提取核心关键词（简化处理）
            core = pattern.replace(r"\s+", " ").replace(r"(.*?)", "").strip("^$")
            kill_keywords.append(core)

    kept = []
    for line in lines:
        line_lower = line.lower()
        should_remove = any(kw in line_lower for kw in kill_keywords if kw)
        if not should_remove:
            kept.append(line)

    result = "\n".join(kept).strip()
    return result if result else text
