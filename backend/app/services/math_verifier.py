"""数学推理验证服务（Phase 4）。

功能：
1. LaTeX 表达式解析（自定义轻量转换器，不依赖 antlr4）
2. 求导验证：sympy diff 对比 AI 给出的导数
3. 积分验证：sympy integrate 对比
4. 极限验证：sympy limit 对比
5. 方程求解验证：sympy solve 对比
6. 数值近似验证：sympy evalf 与答案数值对比
7. 自动验证：根据题目内容自动选择验证方法

设计要点：
- 不使用 sympy.parse_latex（依赖 antlr4 4.11，与 omegaconf 冲突）
- 自研轻量 LaTeX→Python 表达式转换器，覆盖考研数学常见语法
- 验证失败时返回详细错误信息，不抛出异常（验证是辅助功能）
- 所有验证结果带 confidence 字段，区分"精确匹配"和"近似匹配"
"""
import logging
import re
from typing import Any

import sympy as sp
from sympy import Symbol, symbols, sqrt, sin, cos, tan, log, ln, exp, pi, E, oo, Abs, Matrix

logger = logging.getLogger("ailearn.math_verifier")

# 常用符号
x, y, z, t = symbols('x y z t')
n, m, k = symbols('n m k', integer=True)
_SYMBOL_MAP = {'x': x, 'y': y, 'z': z, 't': t, 'n': n, 'm': m, 'k': k}


# ============================================================
# LaTeX → Python/sympy 表达式转换器
# ============================================================

def latex_to_python(latex_str: str) -> str:
    """将 LaTeX 数学表达式转换为 Python/sympy 可解析的表达式。

    覆盖考研数学常见语法：分数、根号、上下标、三角函数、对数、
    极限、积分（基础形式）、希腊字母、关系符等。

    Args:
        latex_str: LaTeX 表达式字符串（不含 $ 包裹）

    Returns:
        Python 表达式字符串，可被 sympy.sympify 解析
    """
    s = latex_str.strip()
    # 去除 $ 包裹
    s = s.strip('$').strip()

    # 1. 分数 \frac{a}{b} → (a)/(b)
    while '\\frac' in s:
        s = re.sub(
            r'\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}',
            r'((\1)/(\2))',
            s
        )
    # 处理 dfrac
    while '\\dfrac' in s:
        s = re.sub(r'\\dfrac\s*\{([^{}]+)\}\s*\{([^{}]+)\}', r'((\1)/(\2))', s)

    # 2. 根号 \sqrt{x} → sqrt(x), \sqrt[n]{x} → root(x,n)
    s = re.sub(r'\\sqrt\s*\[([^\]]+)\]\s*\{([^{}]+)\}', r'root(\2,\1)', s)
    s = re.sub(r'\\sqrt\s*\{([^{}]+)\}', r'sqrt(\1)', s)

    # 3. 三角函数和常用函数（带反函数）
    _func_map = {
        '\\sin': 'sin', '\\cos': 'cos', '\\tan': 'tan',
        '\\cot': 'cot', '\\sec': 'sec', '\\csc': 'csc',
        '\\arcsin': 'asin', '\\arccos': 'acos', '\\arctan': 'atan',
        '\\sinh': 'sinh', '\\cosh': 'cosh', '\\tanh': 'tanh',
        '\\log': 'log', '\\ln': 'ln', '\\exp': 'exp',
        '\\abs': 'Abs', '\\max': 'Max', '\\min': 'Min',
    }
    for latex_func, py_func in _func_map.items():
        # 匹配 \func{...} 或 \func(...) 或 \func x
        s = re.sub(rf'{re.escape(latex_func)}\s*\{{([^{{}}]+)\}}', rf'{py_func}(\1)', s)
        s = re.sub(rf'{re.escape(latex_func)}\s*\(([^)]+)\)', rf'{py_func}(\1)', s)

    # 4. 希腊字母
    _greek_map = {
        '\\alpha': 'alpha', '\\beta': 'beta', '\\gamma': 'gamma',
        '\\delta': 'delta', '\\epsilon': 'epsilon', '\\varepsilon': 'epsilon',
        '\\zeta': 'zeta', '\\eta': 'eta', '\\theta': 'theta',
        '\\vartheta': 'theta', '\\iota': 'iota', '\\kappa': 'kappa',
        '\\lambda': 'lamda', '\\mu': 'mu', '\\nu': 'nu',
        '\\xi': 'xi', '\\omicron': 'omicron', '\\pi': 'pi',
        '\\rho': 'rho', '\\varrho': 'rho', '\\sigma': 'sigma',
        '\\varsigma': 'sigma', '\\tau': 'tau', '\\upsilon': 'upsilon',
        '\\phi': 'phi', '\\varphi': 'phi', '\\chi': 'chi',
        '\\psi': 'psi', '\\omega': 'omega',
        '\\Gamma': 'Gamma', '\\Delta': 'Delta', '\\Theta': 'Theta',
        '\\Lambda': 'Lambda', '\\Xi': 'Xi', '\\Pi': 'Pi',
        '\\Sigma': 'Sigma', '\\Upsilon': 'Upsilon', '\\Phi': 'Phi',
        '\\Psi': 'Psi', '\\Omega': 'Omega',
    }
    for latex_g, py_g in _greek_map.items():
        s = s.replace(latex_g, py_g)

    # 5. 特殊常量
    s = s.replace('\\infty', 'oo')
    s = s.replace('\\e', 'E')
    s = s.replace('\\cdot', '*')
    s = s.replace('\\times', '*')
    s = s.replace('\\div', '/')
    s = s.replace('\\pm', '+/-')  # sympy 不直接支持，简化

    # 6. 关系符（用于方程/不等式）
    s = s.replace('\\leq', '<=')
    s = s.replace('\\le', '<=')
    s = s.replace('\\geq', '>=')
    s = s.replace('\\ge', '>=')
    s = s.replace('\\neq', '!=')
    s = s.replace('\\ne', '!=')
    s = s.replace('\\approx', '==')  # 近似等于简化为等于

    # 7. 去除 \left \right
    s = s.replace('\\left', '').replace('\\right', '')

    # 8. 上标 ^ 和下标 _ 处理
    # ^{...} → **(...)
    s = re.sub(r'\^\s*\{([^{}]+)\}', r'**(\1)', s)
    # ^x → **x
    s = re.sub(r'\^\s*([a-zA-Z0-9])', r'**\1', s)
    # _{...} → _...（sympy 符号名支持下划线）
    s = re.sub(r'_\s*\{([^{}]+)\}', r'_\1', s)

    # 9. 极限 \lim_{x \to a} f(x) → 特殊标记，由验证函数处理
    # 积分 \int_{a}^{b} f(x) dx → 特殊标记
    # 这些高级结构在具体验证函数中单独解析

    # 10. 清理多余空格和反斜杠
    s = re.sub(r'\\([a-zA-Z]+)', r'\1', s)  # 去除剩余的命令反斜杠

    # 11. 隐式乘法转换（关键修复）
    # 数字+字母: 2x -> 2*x, 3x^2 -> 3*x^2
    s = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', s)
    # 数字+左括号: 2(x+1) -> 2*(x+1)
    s = re.sub(r'(\d)\(', r'\1*(', s)
    # 右括号+数字: (x+1)2 -> (x+1)*2
    s = re.sub(r'\)(\d)', r')*\1', s)
    # 右括号+左括号: (x+1)(x-1) -> (x+1)*(x-1)
    s = re.sub(r'\)\(', r')*(', s)
    # 右括号+字母: (x+1)x -> (x+1)*x
    s = re.sub(r'\)([a-zA-Z])', r')*\1', s)
    # 字母+左括号（函数调用除外，常见函数已在前面处理）: x(x+1) -> x*(x+1)
    # 注意：sin/cos/log 等已转换为 sin(...) 形式，不会被误处理
    s = re.sub(r'([a-zA-Z])\(', r'\1*(', s)
    # 但要修复被误加的函数调用乘法: sin*(x) -> sin(x)
    for func in ['sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'asin', 'acos', 'atan',
                  'sinh', 'cosh', 'tanh', 'log', 'ln', 'exp', 'sqrt', 'Abs', 'Max', 'Min', 'root']:
        s = s.replace(f'{func}*(', f'{func}(')

    s = s.replace(' ', '')

    return s


def safe_sympify(expr_str: str) -> sp.Expr | None:
    """安全地将字符串转换为 sympy 表达式，失败返回 None。"""
    try:
        # 先尝试直接 sympify
        local_dict = {
            'x': x, 'y': y, 'z': z, 't': t,
            'n': n, 'm': m, 'k': k,
            'sqrt': sqrt, 'sin': sin, 'cos': cos, 'tan': tan,
            'log': log, 'ln': ln, 'exp': exp,
            'pi': pi, 'E': E, 'oo': oo, 'Abs': Abs,
        }
        return sp.sympify(expr_str, locals=local_dict)
    except Exception as e:
        logger.debug("sympify 失败: %s -> %s", expr_str, e)
        return None


def parse_latex_expr(latex_str: str) -> sp.Expr | None:
    """解析 LaTeX 表达式为 sympy 表达式。

    Args:
        latex_str: LaTeX 表达式

    Returns:
        sympy 表达式，解析失败返回 None
    """
    py_str = latex_to_python(latex_str)
    return safe_sympify(py_str)


# ============================================================
# 验证函数
# ============================================================

def _verify_result(
    valid: bool,
    method: str,
    expected: Any = None,
    actual: Any = None,
    confidence: float = 1.0,
    error: str = "",
) -> dict[str, Any]:
    """构建统一的验证结果。"""
    return {
        "valid": valid,
        "method": method,
        "expected": str(expected) if expected is not None else "",
        "actual": str(actual) if actual is not None else "",
        "confidence": confidence,
        "error": error,
    }


def verify_derivative(func_latex: str, derivative_latex: str, var: str = 'x') -> dict[str, Any]:
    """验证求导结果。

    Args:
        func_latex: 原函数 LaTeX
        derivative_latex: 待验证的导数 LaTeX
        var: 求导变量

    Returns:
        验证结果
    """
    func = parse_latex_expr(func_latex)
    deriv = parse_latex_expr(derivative_latex)

    if func is None:
        return _verify_result(False, "derivative", error=f"无法解析原函数: {func_latex}")
    if deriv is None:
        return _verify_result(False, "derivative", error=f"无法解析导数: {derivative_latex}")

    v = _SYMBOL_MAP.get(var, Symbol(var))
    try:
        expected = sp.diff(func, v)
        # 化简后比较
        expected_simplified = sp.simplify(expected)
        actual_simplified = sp.simplify(deriv)
        diff = sp.simplify(expected_simplified - actual_simplified)

        if diff == 0:
            return _verify_result(True, "derivative", expected_simplified, actual_simplified, confidence=1.0)

        # 数值验证（取几个点验证）
        try:
            numeric_match = True
            for val in [0.5, 1.0, 2.0, -1.0]:
                try:
                    e_val = float(expected_simplified.subs(v, val))
                    a_val = float(actual_simplified.subs(v, val))
                    if abs(e_val - a_val) > 1e-6 * (1 + abs(e_val)):
                        numeric_match = False
                        break
                except (TypeError, ValueError):
                    continue
            if numeric_match:
                return _verify_result(True, "derivative", expected_simplified, actual_simplified, confidence=0.8)
        except Exception:
            pass

        return _verify_result(False, "derivative", expected_simplified, actual_simplified, confidence=0.0,
                              error=f"导数不匹配，差值: {diff}")
    except Exception as e:
        return _verify_result(False, "derivative", error=f"求导计算失败: {e}")


def verify_integral(func_latex: str, integral_latex: str, var: str = 'x') -> dict[str, Any]:
    """验证不定积分结果（通过对结果求导对比原函数）。

    Args:
        func_latex: 被积函数 LaTeX
        integral_latex: 待验证的积分结果 LaTeX
        var: 积分变量

    Returns:
        验证结果
    """
    func = parse_latex_expr(func_latex)
    integral = parse_latex_expr(integral_latex)

    if func is None:
        return _verify_result(False, "integral", error=f"无法解析被积函数: {func_latex}")
    if integral is None:
        return _verify_result(False, "integral", error=f"无法解析积分结果: {integral_latex}")

    v = _SYMBOL_MAP.get(var, Symbol(var))
    try:
        # 对积分结果求导，应等于原函数
        derivative_of_integral = sp.diff(integral, v)
        diff = sp.simplify(derivative_of_integral - func)

        if diff == 0:
            return _verify_result(True, "integral", func, integral, confidence=1.0)

        # 数值验证
        try:
            numeric_match = True
            for val in [0.5, 1.0, 2.0]:
                try:
                    e_val = float(func.subs(v, val))
                    a_val = float(derivative_of_integral.subs(v, val))
                    if abs(e_val - a_val) > 1e-6 * (1 + abs(e_val)):
                        numeric_match = False
                        break
                except (TypeError, ValueError):
                    continue
            if numeric_match:
                return _verify_result(True, "integral", func, integral, confidence=0.8)
        except Exception:
            pass

        return _verify_result(False, "integral", func, integral, confidence=0.0,
                              error=f"积分结果求导后与原函数不匹配，差值: {diff}")
    except Exception as e:
        return _verify_result(False, "integral", error=f"积分验证失败: {e}")


def verify_limit(func_latex: str, limit_value: str, var: str = 'x', point: str = 'oo') -> dict[str, Any]:
    """验证极限结果。

    Args:
        func_latex: 函数 LaTeX
        limit_value: 待验证的极限值 LaTeX
        var: 变量
        point: 极限点（oo, 0, a 等）

    Returns:
        验证结果
    """
    func = parse_latex_expr(func_latex)
    expected_val = parse_latex_expr(limit_value)

    if func is None:
        return _verify_result(False, "limit", error=f"无法解析函数: {func_latex}")
    if expected_val is None:
        return _verify_result(False, "limit", error=f"无法解析极限值: {limit_value}")

    v = _SYMBOL_MAP.get(var, Symbol(var))
    point_expr = parse_latex_expr(point) if point not in ('oo', 'inf') else oo

    try:
        actual = sp.limit(func, v, point_expr if point_expr is not None else oo)
        diff = sp.simplify(actual - expected_val)

        if diff == 0:
            return _verify_result(True, "limit", expected_val, actual, confidence=1.0)

        # 数值近似
        try:
            actual_num = float(actual.evalf())
            expected_num = float(expected_val.evalf())
            if abs(actual_num - expected_num) < 1e-6 * (1 + abs(actual_num)):
                return _verify_result(True, "limit", expected_val, actual, confidence=0.9)
        except (TypeError, ValueError):
            pass

        return _verify_result(False, "limit", expected_val, actual, confidence=0.0,
                              error=f"极限值不匹配，差值: {diff}")
    except Exception as e:
        return _verify_result(False, "limit", error=f"极限计算失败: {e}")


def verify_numeric(expression_latex: str, expected_value: float, tolerance: float = 1e-4) -> dict[str, Any]:
    """数值近似验证。

    Args:
        expression_latex: 表达式 LaTeX
        expected_value: 期望的数值答案
        tolerance: 容差

    Returns:
        验证结果
    """
    expr = parse_latex_expr(expression_latex)
    if expr is None:
        return _verify_result(False, "numeric", error=f"无法解析表达式: {expression_latex}")

    try:
        actual = float(expr.evalf())
        diff = abs(actual - expected_value)
        rel_tol = tolerance * (1 + abs(expected_value))

        if diff < rel_tol:
            return _verify_result(True, "numeric", expected_value, actual, confidence=0.95)
        else:
            return _verify_result(False, "numeric", expected_value, actual, confidence=0.0,
                                  error=f"数值不匹配，差值 {diff:.6f} 超过容差 {rel_tol:.6f}")
    except (TypeError, ValueError) as e:
        return _verify_result(False, "numeric", error=f"数值计算失败: {e}")


def verify_equation(equation_latex: str, solution_latex: str, var: str = 'x') -> dict[str, Any]:
    """验证方程的解。

    Args:
        equation_latex: 方程 LaTeX（如 x^2 - 5x + 6 = 0）
        solution_latex: 待验证的解 LaTeX（如 x=2 或 2,3）
        var: 变量

    Returns:
        验证结果
    """
    # 解析方程（分离左右两边）
    if '=' in equation_latex:
        parts = equation_latex.split('=', 1)
        lhs = parse_latex_expr(parts[0])
        rhs = parse_latex_expr(parts[1])
        if lhs is None or rhs is None:
            return _verify_result(False, "equation", error=f"无法解析方程: {equation_latex}")
        equation_expr = sp.Eq(lhs, rhs)
    else:
        # 假设表达式等于0
        expr = parse_latex_expr(equation_latex)
        if expr is None:
            return _verify_result(False, "equation", error=f"无法解析方程: {equation_latex}")
        equation_expr = sp.Eq(expr, 0)

    v = _SYMBOL_MAP.get(var, Symbol(var))

    try:
        solutions = sp.solve(equation_expr, v)
        if not solutions:
            return _verify_result(False, "equation", error="方程无解")

        # 解析待验证的解
        solution_str = solution_latex.strip()
        # 处理 x=2 或 x=2,3 格式
        solution_str = re.sub(r'^[a-zA-Z]\s*=\s*', '', solution_str)
        solution_vals = [s.strip() for s in re.split(r'[,，]', solution_str) if s.strip()]

        parsed_solutions = []
        for sv in solution_vals:
            parsed = parse_latex_expr(sv)
            if parsed is not None:
                parsed_solutions.append(parsed)

        if not parsed_solutions:
            return _verify_result(False, "equation", error=f"无法解析解: {solution_latex}")

        # 验证每个解是否在解集中
        all_match = True
        for ps in parsed_solutions:
            match = any(sp.simplify(ps - s) == 0 for s in solutions)
            if not match:
                all_match = False
                break

        if all_match and len(parsed_solutions) == len(solutions):
            return _verify_result(True, "equation", solutions, parsed_solutions, confidence=1.0)
        elif all_match:
            return _verify_result(True, "equation", solutions, parsed_solutions, confidence=0.7,
                                  error="解正确但可能不完整")
        else:
            return _verify_result(False, "equation", solutions, parsed_solutions, confidence=0.0,
                                  error="解不正确")
    except Exception as e:
        return _verify_result(False, "equation", error=f"方程求解失败: {e}")


# ============================================================
# 自动验证
# ============================================================

def auto_verify(question: str, answer: str, qtype: str = "short") -> dict[str, Any]:
    """根据题目内容自动选择验证方法。

    识别规则：
    - 含"导数"/"求导"/"dy/dx" → 求导验证
    - 含"积分"/"∫"/"原函数" → 积分验证
    - 含"极限"/"lim"/"→" → 极限验证
    - 含"="且答案是数值/简单表达式 → 方程验证
    - 答案是纯数字 → 数值验证

    Args:
        question: 题目文本
        answer: 待验证的答案
        qtype: 题型

    Returns:
        验证结果（含 method 字段说明用了哪种验证方法）
    """
    q = question.lower()

    # 求导验证
    if any(kw in q for kw in ['导数', '求导', "dy/dx", "y'", '微分']):
        # 尝试从题目中提取原函数（简单规则："求...的导数"）
        # 如果无法提取，返回不支持自动验证
        return _verify_result(False, "auto", error="求导题需要手动指定原函数和导数，调用 verify_derivative")

    # 积分验证
    if any(kw in q for kw in ['积分', '∫', '原函数', '不定积分']):
        return _verify_result(False, "auto", error="积分题需要手动指定被积函数和结果，调用 verify_integral")

    # 极限验证
    if any(kw in q for kw in ['极限', 'lim', '→', '趋近']):
        return _verify_result(False, "auto", error="极限题需要手动指定函数和极限点，调用 verify_limit")

    # 数值验证（答案是纯数字）
    try:
        num_answer = float(answer.replace(',', ''))
        # 尝试从题目中提取表达式（简单规则）
        # 如果题目中包含可计算的表达式，进行数值验证
        return _verify_result(False, "auto", error=f"数值答案 {num_answer}，需要手动指定表达式，调用 verify_numeric")
    except (ValueError, TypeError):
        pass

    # 方程验证
    if '=' in question and any(kw in q for kw in ['方程', '求解', '解为', '根为']):
        return _verify_result(False, "auto", error="方程题需要手动指定方程和解，调用 verify_equation")

    return _verify_result(False, "auto", error="无法自动识别题型，请使用具体的验证函数")


def get_capabilities() -> dict[str, Any]:
    """获取支持的验证能力列表。"""
    return {
        "methods": [
            {"id": "derivative", "name": "求导验证", "description": "sympy diff 对比，支持精确匹配和数值验证"},
            {"id": "integral", "name": "积分验证", "description": "对积分结果求导对比原函数"},
            {"id": "limit", "name": "极限验证", "description": "sympy limit 计算对比"},
            {"id": "numeric", "name": "数值验证", "description": "sympy evalf 数值近似对比"},
            {"id": "equation", "name": "方程求解验证", "description": "sympy solve 求解对比"},
            {"id": "auto", "name": "自动识别", "description": "根据题目关键词自动选择验证方法（有限支持）"},
        ],
        "latex_support": "轻量转换器，支持分数、根号、上下标、三角函数、对数、希腊字母、关系符等考研数学常见语法",
        "limitations": [
            "不支持复杂的多重积分、曲线积分、曲面积分",
            "不支持级数展开验证",
            "LaTeX 转换器为轻量实现，复杂嵌套可能解析失败",
            "自动识别仅支持关键词匹配，复杂题目需手动指定验证方法",
        ],
    }
