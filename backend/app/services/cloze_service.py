"""挖空背诵服务：AI生成挖空题、评分、任务联动。

挖空题（Cloze）是一种填空题，AI根据知识点内容生成带空格的题干，
用户填写答案后由AI评分。

任务联动规则：
- 挖空得分 >= 91 才能认定任务完成（高标准）
- 挖空和测题得分都 >= 83 时视为完成任务（双达标）
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_gateway import AiGatewayError, chat_stream
from ..models import Conversation, KnowledgeNode, QuizAnswer, QuizSession, Task
from ..models.enums import TaskStatus

logger = logging.getLogger("ailearn.cloze")

# 挖空题通过分数（高标准）
CLOZE_PASS_SCORE = 91
# 双达标分数（挖空和测题都达到此分数视为完成）
DUAL_PASS_SCORE = 83


def select_node_for_cloze(db: Session, conv: Conversation) -> KnowledgeNode | None:
    """自动选择最合适的知识点用于挖空题。

    优先级：
    1. 当前学习中/待完成任务关联的知识点
    2. 当前活跃知识点（最近出题使用的知识点）
    3. 课程内薄弱知识点（掌握度最低的）
    4. 课程内第一个知识点
    """
    from ..models import Course, StudySession, Task

    # 优先级1：从当前任务列表中选择
    if conv.session_id:
        task = db.scalar(
            select(Task)
            .where(
                Task.session_id == conv.session_id,
                Task.status.in_([TaskStatus.TODO, TaskStatus.DOING]),
                Task.target_knowledge_id.isnot(None),
            )
            .order_by(Task.seq, Task.id)
            .limit(1)
        )
        if task and task.target_knowledge_id:
            node = db.get(KnowledgeNode, task.target_knowledge_id)
            if node:
                logger.info("挖空题自动选择知识点（任务）: %s", node.name)
                return node

    # 优先级2：从最近的出题记录中选择
    # 这里简化处理，直接从薄弱知识点中选择

    # 优先级3：课程内薄弱知识点
    if conv.course_id:
        weak_nodes = list(db.scalars(
            select(KnowledgeNode)
            .where(KnowledgeNode.subject_id == conv.course_id)
            .order_by(KnowledgeNode.mastery.asc())
            .limit(5)
        ))
        if weak_nodes:
            # 选择掌握度最低且有内容的知识点
            for node in weak_nodes:
                if node.summary or node.notes:
                    logger.info("挖空题自动选择知识点（薄弱）: %s", node.name)
                    return node
            # 如果都没有内容，选择第一个
            logger.info("挖空题自动选择知识点（薄弱第一个）: %s", weak_nodes[0].name)
            return weak_nodes[0]

    # 优先级4：课程内第一个知识点
    if conv.course_id:
        first_node = db.scalar(
            select(KnowledgeNode)
            .where(KnowledgeNode.subject_id == conv.course_id)
            .order_by(KnowledgeNode.id)
            .limit(1)
        )
        if first_node:
            logger.info("挖空题自动选择知识点（第一个）: %s", first_node.name)
            return first_node

    # 最后：任意一个知识点
    any_node = db.scalar(select(KnowledgeNode).order_by(KnowledgeNode.id).limit(1))
    return any_node


def _build_rich_node_content(db: Session, node: KnowledgeNode) -> str:
    """构建丰富的知识点内容，用于挖空题生成。

    包括：知识点名称、摘要、学习笔记、细化参数表、关联题目内容。
    """
    from ..models import QuizQuestion

    parts = [f"【知识点名称】{node.name}"]

    if node.summary:
        parts.append(f"【知识点摘要】{node.summary}")

    # 解析学习笔记（可能包含细化参数表JSON）
    if node.notes:
        try:
            notes_data = json.loads(node.notes)
            if isinstance(notes_data, dict):
                params = notes_data.get("params", {})
                if params:
                    parts.append("【知识点细化参数】")
                    if params.get("definition"):
                        parts.append(f"定义：{params['definition']}")
                    if params.get("core_elements"):
                        if isinstance(params["core_elements"], list):
                            parts.append(f"核心要素：{'、'.join(params['core_elements'])}")
                        else:
                            parts.append(f"核心要素：{params['core_elements']}")
                    if params.get("scope_boundary"):
                        parts.append(f"范围边界：{params['scope_boundary']}")
                    if params.get("key_formulas"):
                        if isinstance(params["key_formulas"], list):
                            parts.append(f"关键公式：{'、'.join(params['key_formulas'])}")
                        else:
                            parts.append(f"关键公式：{params['key_formulas']}")
                    if params.get("typical_examples"):
                        if isinstance(params["typical_examples"], list):
                            parts.append(f"典型例子：{'；'.join(params['typical_examples'])}")
                        else:
                            parts.append(f"典型例子：{params['typical_examples']}")
                    if params.get("common_mistakes"):
                        if isinstance(params["common_mistakes"], list):
                            parts.append(f"常见误区：{'；'.join(params['common_mistakes'])}")
                        else:
                            parts.append(f"常见误区：{params['common_mistakes']}")
                    if params.get("problem_solving_steps"):
                        if isinstance(params["problem_solving_steps"], list):
                            parts.append(f"解题步骤：{' → '.join(params['problem_solving_steps'])}")
                        else:
                            parts.append(f"解题步骤：{params['problem_solving_steps']}")
                else:
                    # notes不是JSON格式，作为普通文本
                    parts.append(f"【学习笔记】{node.notes}")
            else:
                parts.append(f"【学习笔记】{node.notes}")
        except (json.JSONDecodeError, TypeError):
            # notes不是JSON格式，作为普通文本
            parts.append(f"【学习笔记】{node.notes}")

    # 获取关联题目内容（最多3道）
    try:
        questions = list(db.scalars(
            select(QuizQuestion).where(QuizQuestion.node_id == node.id).limit(3)
        ))
        if questions:
            parts.append("【关联题目】")
            for i, q in enumerate(questions, 1):
                try:
                    payload = json.loads(q.payload_json)
                    question_text = payload.get("question", "")
                    if question_text:
                        parts.append(f"题目{i}：{question_text[:200]}")
                        if payload.get("correct_answer"):
                            parts.append(f"答案{i}：{payload['correct_answer']}")
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception:
        pass

    return "\n".join(parts)


async def generate_cloze(
    db: Session,
    conv: Conversation,
    node: KnowledgeNode,
    *,
    blank_count: int = 3,
) -> dict:
    """AI生成挖空题。

    Args:
        db: 数据库会话
        conv: 课堂会话
        node: 知识点节点
        blank_count: 空格数量

    Returns:
        {
            "question": "题干（带____空格）",
            "blanks": [
                {"index": 1, "answer": "标准答案", "hint": "提示"},
                ...
            ],
            "explanation": "解析",
            "node_id": node.id,
            "node_name": node.name,
        }
    """
    # 构建丰富的知识点内容
    node_content = _build_rich_node_content(db, node)

    system_prompt = f"""你是一个专业的挖空题出题老师。根据知识点内容生成挖空填空题。

要求：
1. 生成 {blank_count} 个空格的挖空题
2. 题干要连贯完整，基于知识点内容中的关键概念、定义、公式、性质、步骤
3. 空格用 ____ 表示，每个空格对应一个明确的答案
4. 每个空格的答案必须是知识点中的核心概念、关键术语、重要公式、定义要素或操作步骤
5. 答案要唯一且明确，不能有歧义，不能是长句子
6. 提供每个空格的简短提示（hint），提示不能直接给出答案
7. 提供完整解析，说明每个答案的依据和知识点
8. 题干要覆盖知识点的多个方面，不要只集中在一个点上
9. 挖空题要能有效检验对知识点的理解和记忆

知识点内容：
{node_content}

输出JSON格式（只输出JSON，不要其他文字）：
{{
    "question": "题干，用____表示空格",
    "blanks": [
        {{"index": 1, "answer": "答案1", "hint": "提示1"}},
        {{"index": 2, "answer": "答案2", "hint": "提示2"}}
    ],
    "explanation": "完整解析，说明每个答案的依据"
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请生成挖空题"},
    ]

    parts: list[str] = []
    set_function_type("quiz")
    try:
        async for text in chat_stream(messages):
            parts.append(text)
    except AiGatewayError as e:
        logger.error("挖空题生成失败: %s", e)
        raise

    raw = "".join(parts).strip()
    # 提取JSON（可能包含markdown代码块）
    json_str = _extract_json(raw)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("挖空题JSON解析失败: %s, raw: %s", e, raw[:200])
        raise ValueError(f"挖空题生成失败：AI返回格式错误")

    # 验证必要字段
    if "question" not in result or "blanks" not in result:
        raise ValueError("挖空题生成失败：缺少必要字段")

    result["node_id"] = node.id
    result["node_name"] = node.name
    result["generated_at"] = datetime.now().isoformat()
    return result


async def grade_cloze(
    db: Session,
    cloze: dict,
    user_answers: list[str],
    *,
    task: Optional[Task] = None,
) -> dict:
    """AI评分挖空题。

    Args:
        db: 数据库会话
        cloze: 挖空题数据
        user_answers: 用户答案列表
        task: 关联的任务（可选）

    Returns:
        {
            "score": 0-100,
            "passed": bool,
            "details": [
                {"index": 1, "user_answer": "...", "correct_answer": "...", "correct": bool, "feedback": "..."},
                ...
            ],
            "overall_feedback": "总体反馈",
            "task_updated": bool,
        }
    """
    blanks = cloze.get("blanks", [])
    if len(user_answers) != len(blanks):
        raise ValueError(f"答案数量不匹配：期望{len(blanks)}个，实际{len(user_answers)}个")

    # 构建评分prompt
    blank_details = []
    for i, (blank, user_ans) in enumerate(zip(blanks, user_answers)):
        blank_details.append(
            f"空格{i+1}：\n"
            f"  标准答案：{blank.get('answer', '')}\n"
            f"  用户答案：{user_ans}\n"
            f"  提示：{blank.get('hint', '')}"
        )

    system_prompt = f"""你是一个严格的挖空题评分老师。请根据标准答案和用户答案进行评分。

评分标准：
1. 完全正确（含义相同、拼写正确）→ 该空格满分
2. 部分正确（含义接近但有小错误）→ 该空格50%分
3. 错误或未答 → 该空格0分
4. 总分 = 各空格得分之和 / 空格数 * 100

题目：{cloze.get('question', '')}

{chr(10).join(blank_details)}

输出JSON格式（只输出JSON，不要其他文字）：
{{
    "score": 0-100的整数,
    "passed": true/false（score >= {CLOZE_PASS_SCORE}为通过）,
    "details": [
        {{"index": 1, "user_answer": "用户答案", "correct_answer": "标准答案", "correct": true/false, "feedback": "评分说明"}},
        ...
    ],
    "overall_feedback": "总体反馈和学习建议"
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请评分"},
    ]

    parts: list[str] = []
    set_function_type("quiz_answer")
    try:
        async for text in chat_stream(messages):
            parts.append(text)
    except AiGatewayError as e:
        logger.error("挖空题评分失败: %s", e)
        raise

    raw = "".join(parts).strip()
    json_str = _extract_json(raw)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("挖空题评分JSON解析失败: %s, raw: %s", e, raw[:200])
        # 降级：简单字符串匹配评分
        result = _fallback_grade(blanks, user_answers)

    score = result.get("score", 0)
    passed = score >= CLOZE_PASS_SCORE
    result["passed"] = passed
    result["cloze_pass_score"] = CLOZE_PASS_SCORE

    # 任务联动
    task_updated = False
    if task is not None:
        task_updated = await _update_task_with_cloze_score(db, task, score, passed)
        result["task_updated"] = task_updated
        result["task_status"] = task.status
        result["task_passed"] = task.passed

    return result


async def _update_task_with_cloze_score(
    db: Session, task: Task, cloze_score: int, cloze_passed: bool
) -> bool:
    """根据挖空题得分更新任务状态。

    任务完成规则（双达标）：
    - 挖空得分 >= 83 且 测题得分 >= 83 → 任务完成
    - 挖空得分 >= 91 → 挖空单项达标（高标准）
    - 仅挖空达标但测题未达标 → 任务保持进行中

    Returns:
        bool: 任务状态是否更新
    """
    task.attempts = (task.attempts or 0) + 1

    # 记录挖空得分（存储在task的extra字段或单独字段）
    # 这里用actual_score暂存，实际应该有单独的cloze_score字段
    # 为了简化，我们用quiz_session的得分来判断测题是否达标

    # 检查测题得分（从QuizAnswer中计算平均分）
    quiz_score = None
    if task.quiz_session_id:
        answers = list(db.scalars(
            select(QuizAnswer).where(QuizAnswer.session_id == task.quiz_session_id)
        ))
        if answers:
            scores = [a.score for a in answers if a.score is not None]
            if scores:
                quiz_score = sum(scores) // len(scores)

    # 双达标判断
    cloze_dual_pass = cloze_score >= DUAL_PASS_SCORE
    quiz_dual_pass = quiz_score is not None and quiz_score >= DUAL_PASS_SCORE

    if cloze_dual_pass and quiz_dual_pass:
        # 双达标 → 任务完成
        task.status = TaskStatus.DONE
        task.passed = True
        task.is_overdue = False
        task.actual_score = max(cloze_score, quiz_score or 0)
        logger.info(
            "任务 %d 双达标完成（挖空=%d, 测题=%d）",
            task.id, cloze_score, quiz_score,
        )
        db.commit()
        return True
    elif cloze_passed:
        # 挖空单项达标（>=91），但测题未达标 → 保持进行中
        logger.info(
            "任务 %d 挖空单项达标（%d>=%d），测题未达标（%s），保持进行中",
            task.id, cloze_score, CLOZE_PASS_SCORE, quiz_score,
        )
        db.commit()
        return False
    else:
        # 未达标 → 保持进行中
        logger.info(
            "任务 %d 挖空未达标（%d<%d），保持进行中",
            task.id, cloze_score, CLOZE_PASS_SCORE,
        )
        db.commit()
        return False


def _fallback_grade(blanks: list, user_answers: list) -> dict:
    """降级评分：简单字符串匹配。"""
    details = []
    total_score = 0
    for i, (blank, user_ans) in enumerate(zip(blanks, user_answers)):
        correct_ans = blank.get("answer", "").strip().lower()
        user_ans_clean = user_ans.strip().lower()
        correct = user_ans_clean == correct_ans and user_ans_clean != ""
        if correct:
            total_score += 100
            feedback = "回答正确"
        elif user_ans_clean == "":
            feedback = "未作答"
        else:
            feedback = f"回答错误，正确答案是：{correct_ans}"
        details.append({
            "index": i + 1,
            "user_answer": user_ans,
            "correct_answer": blank.get("answer", ""),
            "correct": correct,
            "feedback": feedback,
        })

    score = total_score // len(blanks) if blanks else 0
    return {
        "score": score,
        "passed": score >= CLOZE_PASS_SCORE,
        "details": details,
        "overall_feedback": "AI评分服务暂时不可用，使用简单匹配评分。建议稍后重试。",
    }


def _extract_json(raw: str) -> str:
    """从AI返回中提取JSON字符串。"""
    # 去除markdown代码块
    if "```json" in raw:
        start = raw.find("```json") + 7
        end = raw.find("```", start)
        if end > start:
            return raw[start:end].strip()
    if "```" in raw:
        start = raw.find("```") + 3
        end = raw.find("```", start)
        if end > start:
            return raw[start:end].strip()
    # 找到第一个{和最后一个}
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1]
    return raw


async def generate_cloze_batch(
    db: Session,
    nodes: list,
    *,
    blank_count: int = 3,
    questions_per_node: int = 1,
    info_collector: dict | None = None,
) -> list:
    """一次AI调用批量生成多道挖空题。

    Args:
        db: 数据库会话
        nodes: 知识点列表（每个节点生成 questions_per_node 道题）
        blank_count: 每道题的空格数
        questions_per_node: 每个知识点生成几道题

    Returns:
        挖空题列表，每道题包含 node_id / node_name
    """
    if not nodes:
        return []

    ai_decides = questions_per_node <= 0
    total_questions = 0 if ai_decides else len(nodes) * questions_per_node
    multi_node = len(nodes) > 1

    node_contents = []
    for i, node in enumerate(nodes, 1):
        content = _build_rich_node_content(db, node)
        node_contents.append(f"===== 知识点{i}（ID:{node.id}，名称：{node.name}）=====\n{content}")

    all_content = "\n\n".join(node_contents)

    if ai_decides:
        if multi_node:
            task_desc = (
                f"为上面 {len(nodes)} 个知识点生成挖空题。请根据每个知识点内容的丰富程度"
                f"自行决定题目数量（内容丰富的多出，内容少的少出），总共建议2-5道。"
                f"每道题必须基于对应知识点的内容，且在结果中通过 node_id 标明来自哪个知识点。"
            )
        else:
            task_desc = (
                f"基于上面的知识点生成挖空题。请根据知识点内容的丰富程度自行决定题目数量，"
                f"建议2-5道（内容丰富可多出，内容较少可少出）。"
                f"每题覆盖知识点的不同方面（定义、性质、公式、应用等），不要重复。"
                f"所有题的 node_id 都填 {nodes[0].id}。"
            )
    elif multi_node:
        task_desc = (
            f"为上面 {len(nodes)} 个知识点各生成 {questions_per_node} 道挖空题，"
            f"共 {total_questions} 道。每道题必须基于对应知识点的内容，"
            f"且在结果中通过 node_id 标明来自哪个知识点。"
        )
    else:
        task_desc = (
            f"基于上面的知识点生成 {total_questions} 道不同的挖空题，"
            f"每题覆盖知识点的不同方面（定义、性质、公式、应用等），不要重复。"
            f"所有题的 node_id 都填 {nodes[0].id}。"
        )

    system_prompt = f"""你是一个专业的挖空题出题老师。{task_desc}

每题要求：
1. 每道题 {blank_count} 个空格，空格用 ____ 表示
2. 题干连贯完整，基于知识点中的关键概念、定义、公式、性质、步骤
3. 每个空格的答案唯一明确，是核心概念/关键术语/重要公式/定义要素，不能是长句子
4. 提供每个空格的简短提示（hint），提示不能直接给出答案
5. 提供完整解析，说明每个答案的依据
6. 每题通过 node_id 字段标明来自哪个知识点（使用上面知识点标题中的ID）

知识点内容：
{all_content}

输出JSON格式（只输出JSON，不要其他文字）：
{{
    "clozes": [
        {{
            "question": "题干，用____表示空格",
            "blanks": [
                {{"index": 1, "answer": "答案1", "hint": "提示1"}},
                {{"index": 2, "answer": "答案2", "hint": "提示2"}}
            ],
            "explanation": "完整解析",
            "node_id": 1
        }}
    ]
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请生成挖空题"},
    ]

    parts = []
    set_function_type("quiz")
    try:
        async for text in chat_stream(messages, info_collector=info_collector):
            parts.append(text)
    except AiGatewayError as e:
        logger.error("批量挖空题生成失败: %s", e)
        raise

    raw = "".join(parts).strip()
    json_str = _extract_json(raw)

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("批量挖空题JSON解析失败: %s, raw: %s", e, raw[:300])
        raise ValueError("批量挖空题生成失败：AI返回格式错误")

    if isinstance(parsed, dict):
        clozes_data = parsed.get("clozes", [])
    elif isinstance(parsed, list):
        clozes_data = parsed
    else:
        clozes_data = []

    if not isinstance(clozes_data, list) or not clozes_data:
        raise ValueError("批量挖空题生成失败：返回为空")

    node_map = {n.id: n for n in nodes}

    results = []
    for i, item in enumerate(clozes_data):
        if not isinstance(item, dict):
            continue
        if "question" not in item or "blanks" not in item:
            continue
        raw_nid = item.get("node_id")
        node = None
        if raw_nid is not None:
            try:
                nid = int(raw_nid)
                if nid in node_map:
                    node = node_map[nid]
                elif 1 <= nid <= len(nodes):
                    node = nodes[nid - 1]
            except (TypeError, ValueError):
                pass
        if node is None:
            node = nodes[min(i, len(nodes) - 1)]

        item["node_id"] = node.id
        item["node_name"] = node.name
        item["question_index"] = i + 1
        item["generated_at"] = datetime.now().isoformat()
        results.append(item)

    if not results:
        raise ValueError("批量挖空题生成失败：无有效题目")

    logger.info("批量挖空题生成成功: %d道（节点%d个）", len(results), len(nodes))
    return results


async def grade_cloze_batch(
    db: Session,
    items: list[dict],
    *,
    task: Optional[Task] = None,
    info_collector: dict | None = None,
) -> dict:
    """一次AI调用批量评分多道挖空题。

    Args:
        db: 数据库会话
        items: [{"cloze": {...}, "user_answers": [...]}, ...]
        task: 关联任务（可选，用平均分更新任务）

    Returns:
        {
            "results": [ {score, passed, details, overall_feedback}, ... ],
            "average_score": int,
            "all_passed": bool,
            "task_updated": bool,
        }
    """
    if not items:
        return {"results": [], "average_score": 0, "all_passed": False, "task_updated": False}

    # 构建所有题目的评分详情
    question_blocks = []
    for idx, item in enumerate(items, 1):
        cloze = item.get("cloze", {})
        user_answers = item.get("user_answers", [])
        blanks = cloze.get("blanks", [])

        blank_details = []
        for j, (blank, user_ans) in enumerate(zip(blanks, user_answers)):
            blank_details.append(
                f"  空格{j+1}：标准答案={blank.get('answer', '')}，用户答案={user_ans}，提示={blank.get('hint', '')}"
            )

        question_blocks.append(
            f"题目{idx}（node_id={cloze.get('node_id', '?')}）：\n"
            f"题干：{cloze.get('question', '')}\n"
            + "\n".join(blank_details)
        )

    all_questions = "\n\n".join(question_blocks)

    system_prompt = f"""你是一个严格的挖空题评分老师。请对以下 {len(items)} 道挖空题逐一评分。

评分标准（每题）：
1. 完全正确（含义相同、拼写正确）→ 该空格满分
2. 部分正确（含义接近但有小错误）→ 该空格50%分
3. 错误或未答 → 该空格0分
4. 每题得分 = 各空格得分之和 / 空格数 * 100，取整数

{all_questions}

输出JSON格式（只输出JSON，不要其他文字）：
{{
    "results": [
        {{
            "score": 0-100的整数,
            "passed": true/false（score >= {CLOZE_PASS_SCORE}为通过）,
            "details": [
                {{"index": 1, "user_answer": "用户答案", "correct_answer": "标准答案", "correct": true/false, "feedback": "评分说明"}},
                ...
            ],
            "overall_feedback": "本题总体反馈和学习建议"
        }},
        ...
    ]
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请评分"},
    ]

    parts = []
    set_function_type("quiz_answer")
    try:
        async for text in chat_stream(messages, info_collector=info_collector):
            parts.append(text)
    except AiGatewayError as e:
        logger.error("批量挖空题评分失败: %s", e)
        raise

    raw = "".join(parts).strip()
    json_str = _extract_json(raw)

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("批量挖空题评分JSON解析失败: %s, raw: %s", e, raw[:300])
        # 降级：逐题简单匹配评分
        results = []
        for item in items:
            cloze = item.get("cloze", {})
            user_answers = item.get("user_answers", [])
            results.append(_fallback_grade(cloze.get("blanks", []), user_answers))
        parsed = {"results": results}

    results_data = parsed.get("results", []) if isinstance(parsed, dict) else parsed
    if not isinstance(results_data, list):
        results_data = []

    # 确保每道题都有结果（不足时用降级评分补齐）
    results = []
    for i, item in enumerate(items):
        if i < len(results_data) and isinstance(results_data[i], dict):
            r = results_data[i]
        else:
            cloze = item.get("cloze", {})
            user_answers = item.get("user_answers", [])
            r = _fallback_grade(cloze.get("blanks", []), user_answers)
        r["passed"] = r.get("score", 0) >= CLOZE_PASS_SCORE
        r["cloze_pass_score"] = CLOZE_PASS_SCORE
        results.append(r)

    # 计算平均分
    scores = [r.get("score", 0) for r in results]
    average_score = sum(scores) // len(scores) if scores else 0
    all_passed = all(r.get("passed", False) for r in results)

    # 任务联动（用平均分）
    task_updated = False
    if task is not None and results:
        task_updated = await _update_task_with_cloze_score(db, task, average_score, all_passed)

    return {
        "results": results,
        "average_score": average_score,
        "all_passed": all_passed,
        "task_updated": task_updated,
        "task_status": task.status if task else None,
        "task_passed": task.passed if task else None,
    }
