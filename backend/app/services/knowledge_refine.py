"""知识点细化服务：为知识点生成结构化参数表，作为模板出题的范围锚。

设计目标：
- 将 AI 自由生成的"知识点名称"升级为结构化参数表，约束出题范围，防止超纲
- 参数表写入 KnowledgeNode.summary（核心定义）和 notes（完整参数 JSON）
- 已细化且质量达标的节点不重复生成（force=True 可强制覆盖）
- 使用 Function Calling 保证输出格式严格稳定（P0 已落地）

参数表字段：
- definition: 核心定义（25-100字，必填）
- core_elements: 核心要素列表（2-5个，必填）
- key_terms: 关键术语列表（1-5个，必填）
- formulas: 相关公式列表（可选，数学/物理/化学等）
- common_mistakes: 常见错误/误区列表（可选，1-3个）
- scope_boundary: 范围边界（本知识点不涉及什么，必填，用于防超纲）
- prerequisites_desc: 前置知识简述（可选）
"""
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeNode
from .call_logger import set_function_type
from .ai_gateway import AiGatewayError, chat_with_tools, extract_tool_arguments

logger = logging.getLogger("ailearn.knowledge_refine")

# 参数表 schema version
PARAMS_SCHEMA_VERSION = "1.0"

# 质量阈值
MIN_DEFINITION_LENGTH = 15  # 定义最少字数
MIN_CORE_ELEMENTS = 2       # 核心要素最少个数
MIN_KEY_TERMS = 1           # 关键术语最少个数

# Function Calling 的 tool 定义
REFINE_TOOL = {
    "type": "function",
    "function": {
        "name": "refine_knowledge_params",
        "description": "为知识点生成结构化参数表，包含定义、核心要素、关键术语、常见错误和范围边界。仅基于知识点本身和其直接前置知识展开，不得涉及延伸、对比或超纲内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "definition": {
                    "type": "string",
                    "description": "核心定义，25-100字，准确、精炼、自包含。必须是本知识点自身的定义，不得引用其他知识点作为定义主体。",
                },
                "core_elements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "核心要素列表，2-5个。每个要素是本知识点的关键组成部分或本质特征，用短语表述。",
                },
                "key_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关键术语列表，1-5个。本知识点涉及的核心专业术语、概念名或符号。",
                },
                "formulas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相关公式列表（可选）。数学/物理/化学/经济学等有公式的学科填写，纯概念类知识点留空数组。",
                },
                "common_mistakes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "常见错误或误区列表（可选），1-3个。学习者容易混淆、记错或理解偏差的点。",
                },
                "scope_boundary": {
                    "type": "string",
                    "description": "范围边界，明确说明本知识点不涉及哪些内容、不深入哪些前置知识的细节、不与哪些相似概念做对比。用于防止出题超纲。",
                },
                "prerequisites_desc": {
                    "type": "string",
                    "description": "前置知识简述（可选）。学习本知识点需要预先掌握的知识，一句话概括即可，不展开细节。",
                },
            },
            "required": ["definition", "core_elements", "key_terms", "scope_boundary"],
        },
    },
}


# ---------------------------------------------------------------------------
# 读取与校验
# ---------------------------------------------------------------------------

def get_refined_params(node: KnowledgeNode) -> dict[str, Any] | None:
    """从节点的 notes 字段解析已有的结构化参数表。

    Returns:
        dict: 参数表，或 None（notes 为空、不是合法 JSON、schema 不匹配、或 params_status=invalid）。
    """
    if not node.notes:
        return None
    try:
        data = json.loads(node.notes)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != PARAMS_SCHEMA_VERSION:
        return None
    # 内容校验失败的参数表不算合格（出题时 fallback 到 AI 自由生成）
    if data.get("params_status") == "invalid":
        return None
    # 旧数据兼容：无 params_status 字段时即时校验，不通过则视为不合格
    if "params_status" not in data:
        params_raw = data.get("params")
        if isinstance(params_raw, dict) and validate_params_content(params_raw):
            return None
    params = data.get("params")
    if not isinstance(params, dict):
        return None
    # 清洗 formulas：AI 可能对无公式知识点生成 "[]"、"null"、空串等脏数据
    formulas = params.get("formulas")
    if isinstance(formulas, list):
        params["formulas"] = [
            f for f in formulas
            if isinstance(f, str)
            and f.strip()
            and f.strip() not in ("[]", "null", "None", "{}", "none")
        ]
    return params


def is_refined(node: KnowledgeNode) -> bool:
    """检查节点是否已有合格的参数表（质量达标）。"""
    params = get_refined_params(node)
    if params is None:
        return False
    return len(validate_params(params)) == 0


def validate_params(params: dict[str, Any]) -> list[str]:
    """校验参数表质量，返回错误列表（空列表=合格）。"""
    errors: list[str] = []

    definition = params.get("definition", "")
    if not isinstance(definition, str) or len(definition.strip()) < MIN_DEFINITION_LENGTH:
        errors.append(f"definition 不能为空且至少 {MIN_DEFINITION_LENGTH} 字")

    core_elements = params.get("core_elements", [])
    if not isinstance(core_elements, list) or len(core_elements) < MIN_CORE_ELEMENTS:
        errors.append(f"core_elements 至少 {MIN_CORE_ELEMENTS} 个")

    key_terms = params.get("key_terms", [])
    if not isinstance(key_terms, list) or len(key_terms) < MIN_KEY_TERMS:
        errors.append(f"key_terms 至少 {MIN_KEY_TERMS} 个")

    scope_boundary = params.get("scope_boundary", "")
    if not isinstance(scope_boundary, str) or not scope_boundary.strip():
        errors.append("scope_boundary 不能为空")

    return errors


# ---------------------------------------------------------------------------
# 内容语义校验（字段类型/语义规范性，严重错误标记 invalid）
# ---------------------------------------------------------------------------

# 公式特征符号（含数学箭头、逻辑符号、希腊字母、上下标等）
_FORMULA_SYMBOLS = set("=+-*/^√∑∫π∞≤≥≠≈%()（）[]{}→⟹⟺⇒⇐⇔∘∀∃εδΔ∇αβγθλμσφω±×÷∛∏∂")
_FORMULA_KEYWORDS = ("O(", "o(", "log", "ln", "sin", "cos", "tan", "exp", "sqrt", "lim", "∂", "Δ", "max", "min", "abs", "floor", "ceil", "round", "gcd", "lcm", "mod")
# 数学上下标字符
_SUBSCRIPT_CHARS = set("₀₁₂₃₄₅₆₇₈₉ₙₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
_SUPERSCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱ⁺⁻⁼⁽⁾")
# 定义中应包含的动词（判断是否是完整句子而非关键词堆砌）—— 仅用于关键词堆砌检测，不单独判错
_DEFINITION_VERBS = ("是", "定义", "表示", "指", "称为", "实现", "构成", "组成", "描述", "反映", "属于", "包含", "包括", "提供", "支持", "通过", "利用", "采用", "建立", "构造", "设计", "执行", "操作", "转换", "映射", "研究", "分析", "计算", "处理", "具备", "完成", "插入", "存储", "读取", "写入", "创建", "销毁", "分配", "释放", "初始化", "更新", "修改", "检查", "验证", "判断", "选择", "评估", "估算", "预测", "推断", "推导", "证明", "检验", "测试", "优化", "改进", "提升", "降低", "提高", "减少", "增加", "扩展", "压缩", "加密", "解密", "编码", "解码", "运行", "启动", "停止", "保存", "加载", "导入", "导出", "复制", "分类", "统计", "汇总", "求解", "求导", "积分", "微分", "极限", "收敛", "发散", "逼近", "近似")
# 边界表述关键词（应该在 scope_boundary，不应在 common_mistakes）
_BOUNDARY_KEYWORDS = ("不涉及", "不讨论", "不深入", "不包括", "不限于", "不展开", "不覆盖", "不包含")
# 前置知识表述（应该在 prerequisites_desc，不应在 common_mistakes/scope_boundary）
_PREREQ_KEYWORDS = ("需了解", "需掌握", "需理解", "需熟悉", "需具备", "需要了解", "需要掌握", "需要理解", "前提是", "基础是")
# 常见错误表述关键词（应该在 common_mistakes）
_MISTAKE_KEYWORDS = ("混淆", "误认为", "容易", "错误", "偏差", "误区", "常常", "往往", "误以为", "搞混", "分不清")


def _looks_like_formula(s: str) -> bool:
    """判断字符串是否像公式（含数学符号/数字+字母组合/函数名）。"""
    if not isinstance(s, str) or not s.strip():
        return False
    s = s.strip()
    # 含等号 → 公式
    if "=" in s:
        return True
    # 含公式关键词
    for kw in _FORMULA_KEYWORDS:
        if kw in s:
            return True
    # 含数学符号（箭头、逻辑符号、希腊字母、上下标等）
    if any(c in _FORMULA_SYMBOLS for c in s):
        return True
    # 含上下标字符
    if any(c in _SUBSCRIPT_CHARS or c in _SUPERSCRIPT_CHARS for c in s):
        return True
    # 纯数字+字母组合（如 2x, O(n), 3n²）
    has_digit = any(c.isdigit() for c in s)
    has_alpha = any(c.isalpha() for c in s)
    if has_digit and has_alpha and len(s) <= 30:
        return True
    # 含冒号+箭头（如 f: A→B）
    if ":" in s and ("→" in s or "->" in s or "⟶" in s):
        return True
    return False


def validate_params_content(params: dict[str, Any]) -> list[str]:
    """内容语义校验，返回严重错误列表（非空则参数表应标记 invalid）。

    校验维度：
    - formulas：非空时每项必须像公式，不能是纯文字描述
    - key_terms：不能是脏数据（"[]"/"null"等），每项长度合理
    - definition：不能是关键词堆砌（|分隔），不能以参见/类似开头，必须含动词
    - common_mistakes：不能含边界表述（不涉及/不讨论）或前置知识表述
    - scope_boundary：不能是常见错误描述或前置知识描述
    """
    errors: list[str] = []

    # 1. formulas 校验
    formulas = params.get("formulas", [])
    if isinstance(formulas, list):
        for i, f in enumerate(formulas):
            if not isinstance(f, str) or not f.strip():
                continue
            if not _looks_like_formula(f):
                errors.append(f"formulas[{i}] 不像公式（纯文字描述）: {f[:30]}")

    # 2. key_terms 校验
    key_terms = params.get("key_terms", [])
    if isinstance(key_terms, list):
        for i, kt in enumerate(key_terms):
            if not isinstance(kt, str):
                errors.append(f"key_terms[{i}] 不是字符串")
                continue
            kt_stripped = kt.strip()
            if kt_stripped in ("[]", "null", "None", "{}", "none", ""):
                errors.append(f"key_terms[{i}] 是脏数据: {kt_stripped}")
            elif len(kt_stripped) > 50:
                errors.append(f"key_terms[{i}] 过长（术语应为短语，≤50字）: {kt_stripped[:30]}")

    # 3. definition 校验
    definition = params.get("definition", "")
    if isinstance(definition, str) and definition.strip():
        d = definition.strip()
        # 不能以参见/类似/详见/参考开头
        if any(d.startswith(prefix) for prefix in ("参见", "类似", "详见", "参考", "见")):
            errors.append(f"definition 以引用词开头，不是自身定义: {d[:30]}")
        # 关键词堆砌检测：含 | 且分割后每段都短，且无动词且无标点
        if "|" in d:
            parts = [p.strip() for p in d.split("|") if p.strip()]
            if len(parts) >= 2 and all(len(p) < 15 for p in parts):
                has_verb = any(v in d for v in _DEFINITION_VERBS)
                has_punct = any(p in d for p in "，。；：、！？")
                if not has_verb and not has_punct:
                    errors.append(f"definition 疑似关键词堆砌（|分隔且无动词无标点）: {d[:40]}")

    # 4. common_mistakes 校验
    common_mistakes = params.get("common_mistakes", [])
    if isinstance(common_mistakes, list):
        for i, cm in enumerate(common_mistakes):
            if not isinstance(cm, str) or not cm.strip():
                continue
            cm_stripped = cm.strip()
            # 不能含边界表述（但如果是在描述错误概念则允许）
            is_describing_mistake = any(kw in cm_stripped for kw in _MISTAKE_KEYWORDS)
            if not is_describing_mistake and any(kw in cm_stripped for kw in _BOUNDARY_KEYWORDS):
                errors.append(f"common_mistakes[{i}] 含边界表述（应在 scope_boundary）: {cm_stripped[:30]}")
            # 不能是前置知识表述
            if any(kw in cm_stripped for kw in _PREREQ_KEYWORDS):
                errors.append(f"common_mistakes[{i}] 含前置知识表述（应在 prerequisites_desc）: {cm_stripped[:30]}")

    # 5. scope_boundary 校验
    scope_boundary = params.get("scope_boundary", "")
    if isinstance(scope_boundary, str) and scope_boundary.strip():
        sb = scope_boundary.strip()
        # 不能是常见错误描述
        if any(kw in sb for kw in _MISTAKE_KEYWORDS) and not any(kw in sb for kw in _BOUNDARY_KEYWORDS):
            errors.append(f"scope_boundary 疑似常见错误描述（应在 common_mistakes）: {sb[:30]}")
        # 不能是前置知识描述
        if any(kw in sb for kw in _PREREQ_KEYWORDS):
            errors.append(f"scope_boundary 含前置知识表述（应在 prerequisites_desc）: {sb[:30]}")

    return errors


# ---------------------------------------------------------------------------
# 上下文构建
# ---------------------------------------------------------------------------

def get_parent_path(db: Session, node: KnowledgeNode) -> list[str]:
    """获取从根节点到当前节点的路径名称列表（用于让 AI 知道层级位置）。"""
    path: list[str] = []
    current = node
    visited = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        path.append(current.name)
        if current.parent_id is None:
            break
        current = db.get(KnowledgeNode, current.parent_id)
    path.reverse()
    return path


def get_siblings(db: Session, node: KnowledgeNode, limit: int = 8) -> list[KnowledgeNode]:
    """获取同级兄弟节点（同 parent_id 的其他节点），用于干扰项生成和边界区分。"""
    if node.parent_id is None:
        # 根节点的兄弟：同 subject_id 的其他根节点
        stmt = (
            select(KnowledgeNode)
            .where(
                KnowledgeNode.parent_id.is_(None),
                KnowledgeNode.subject_id == node.subject_id,
                KnowledgeNode.id != node.id,
            )
            .order_by(KnowledgeNode.sort, KnowledgeNode.id)
            .limit(limit)
        )
    else:
        stmt = (
            select(KnowledgeNode)
            .where(
                KnowledgeNode.parent_id == node.parent_id,
                KnowledgeNode.id != node.id,
            )
            .order_by(KnowledgeNode.sort, KnowledgeNode.id)
            .limit(limit)
        )
    return list(db.scalars(stmt))


# ---------------------------------------------------------------------------
# 核心：细化知识点
# ---------------------------------------------------------------------------

async def refine_node(
    db: Session,
    node_id: int,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """为知识点生成结构化参数表并保存。

    Args:
        node_id: 知识点节点 ID
        force: True 时即使已有合格参数表也重新生成

    Returns:
        dict: 生成的参数表

    Raises:
        ValueError: 知识点不存在
        AiGatewayError: AI 调用失败
    """
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")

    # 已有合格参数表且不强制 → 直接返回
    if not force and is_refined(node):
        logger.info("refine_node: node %d 已有合格参数表，跳过", node_id)
        return get_refined_params(node)

    # 构建上下文
    parent_path = get_parent_path(db, node)
    siblings = get_siblings(db, node)
    sibling_names = [s.name for s in siblings]

    # 构建 messages
    path_str = " > ".join(parent_path) if parent_path else node.name
    sibling_str = "、".join(sibling_names) if sibling_names else "（无）"

    system_prompt = (
        "你是一个知识点细化专家。你的任务是为给定的知识点生成结构化参数表。"
        "严格遵守以下规则：\n"
        "1. 仅基于知识点本身和其直接前置知识展开，不得涉及延伸、拓展、应用场景或跨章节对比\n"
        "2. definition 必须是本知识点自身的定义，不能用'参见XX'或'与XX类似'等表述\n"
        "3. scope_boundary 必须明确说明本知识点不涉及哪些内容，这是防止出题超纲的关键\n"
        "4. 所有字段使用中文（公式、符号、专有名词除外）\n"
        "5. 不要输出任何额外文字，只通过 refine_knowledge_params 工具返回结构化数据"
    )

    user_prompt = (
        f"请细化以下知识点：\n\n"
        f"知识点名称：{node.name}\n"
        f"知识树路径：{path_str}\n"
        f"同级兄弟节点（用于边界区分，不要混入这些概念）：{sibling_str}\n"
        f"节点难度：{node.difficulty}/5\n\n"
        f"请调用 refine_knowledge_params 工具生成结构化参数表。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 调用 AI（Function Calling）
    try:
        set_function_type("knowledge")
        result = await chat_with_tools(
            messages,
            tools=[REFINE_TOOL],
            tool_choice={"type": "function", "function": {"name": "refine_knowledge_params"}},
            temperature=0.3,
            db=db,
        )
    except AiGatewayError:
        raise

    # 提取参数
    params = extract_tool_arguments(result)
    if not params:
        raise ValueError("AI 细化知识点失败：未返回有效参数")

    # 校验质量（格式 + 内容语义）
    errors = validate_params(params)
    if errors:
        logger.warning("refine_node: node %d 参数表格式校验警告: %s", node_id, errors)

    content_errors = validate_params_content(params)
    params_status = "invalid" if content_errors else "valid"
    if content_errors:
        logger.warning(
            "refine_node: node %d 参数表内容校验失败(%d项，标记invalid): %s",
            node_id, len(content_errors), content_errors[:3],
        )

    # 保存到节点
    full_data = {
        "schema_version": PARAMS_SCHEMA_VERSION,
        "refined_at": _now_iso(),
        "params_status": params_status,
        "content_errors": content_errors,
        "params": params,
    }
    node.summary = params.get("definition", node.summary or "")
    node.notes = json.dumps(full_data, ensure_ascii=False)
    db.commit()
    db.refresh(node)

    logger.info(
        "refine_node: node %d 细化完成, status=%s, definition=%d字, elements=%d, terms=%d",
        node_id,
        params_status,
        len(params.get("definition", "")),
        len(params.get("core_elements", [])),
        len(params.get("key_terms", [])),
    )
    return params


async def ensure_refined(db: Session, node_id: int) -> dict[str, Any]:
    """确保节点已细化，返回参数表。如果未细化则即时生成。"""
    node = db.get(KnowledgeNode, node_id)
    if not node:
        raise ValueError(f"知识点不存在: {node_id}")
    if is_refined(node):
        return get_refined_params(node)
    return await refine_node(db, node_id)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 批量预细化
# ---------------------------------------------------------------------------

async def batch_refine_course(
    db: Session,
    course_id: int,
    *,
    force: bool = False,
    delay: float = 1.0,
    only_invalid: bool = True,
    progress_callback=None,
) -> dict:
    """批量细化某个课程的所有 level>=3 知识点。

    Args:
        course_id: 课程ID
        force: True时即使已有valid参数表也重新细化
        delay: 每个请求之间的延迟（秒），避免API限流
        only_invalid: True时只细化invalid参数表的知识点（默认）
        progress_callback: 进度回调函数 callback(current, total, node_name, status)

    Returns:
        dict: 统计信息 {total, success, failed, skipped, details}
    """
    import asyncio
    from ..models import KnowledgeNode
    from sqlalchemy import select

    nodes = list(db.scalars(
        select(KnowledgeNode).where(
            KnowledgeNode.subject_id == course_id,
            KnowledgeNode.level >= 3,
        ).order_by(KnowledgeNode.id)
    ))

    total = len(nodes)
    success = 0
    failed = 0
    skipped = 0
    details = []

    for i, node in enumerate(nodes):
        # 跳过已细化且不强制的
        if not force and is_refined(node):
            skipped += 1
            if progress_callback:
                progress_callback(i + 1, total, node.name, "skipped")
            continue

        # only_invalid模式：只细化有invalid参数表的
        if only_invalid and not force:
            need_refine = False
            if node.notes:
                try:
                    data = json.loads(node.notes)
                    if data.get("params_status") == "invalid":
                        need_refine = True
                except (json.JSONDecodeError, TypeError):
                    pass
            if not need_refine:
                skipped += 1
                if progress_callback:
                    progress_callback(i + 1, total, node.name, "skipped")
                continue

        # 执行细化
        try:
            await refine_node(db, node.id, force=True)
            success += 1
            status = "success"
        except Exception as e:
            failed += 1
            status = "failed"
            details.append({"id": node.id, "name": node.name, "error": str(e)[:100]})

        if progress_callback:
            progress_callback(i + 1, total, node.name, status)

        # 限速
        if delay > 0 and i < total - 1:
            await asyncio.sleep(delay)

    return {
        "course_id": course_id,
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "details": details,
    }


def get_refine_stats(db: Session, course_id: int | None = None) -> dict:
    """统计知识点细化情况。

    Args:
        course_id: 课程ID，None则统计所有课程

    Returns:
        dict: {total, valid, invalid, unrefined, by_course: [...]}
    """
    from ..models import KnowledgeNode, Course
    from sqlalchemy import select

    stmt = select(KnowledgeNode).where(KnowledgeNode.level >= 3)
    if course_id:
        stmt = stmt.where(KnowledgeNode.subject_id == course_id)

    nodes = list(db.scalars(stmt))
    total = len(nodes)
    valid = 0
    invalid = 0
    unrefined = 0

    for node in nodes:
        if is_refined(node):
            valid += 1
        elif node.notes:
            try:
                data = json.loads(node.notes)
                if data.get("params_status") == "invalid":
                    invalid += 1
                else:
                    unrefined += 1
            except (json.JSONDecodeError, TypeError):
                unrefined += 1
        else:
            unrefined += 1

    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "unrefined": unrefined,
    }
