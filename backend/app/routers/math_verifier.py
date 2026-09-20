"""数学验证 API（Phase 4）。

端点：
- POST /api/v1/math/verify/derivative   求导验证
- POST /api/v1/math/verify/integral     积分验证
- POST /api/v1/math/verify/limit        极限验证
- POST /api/v1/math/verify/numeric      数值验证
- POST /api/v1/math/verify/equation     方程求解验证
- POST /api/v1/math/verify/auto         自动识别验证
- GET  /api/v1/math/capabilities        支持的验证能力
- POST /api/v1/math/parse                LaTeX 表达式解析测试
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..services.math_verifier import (
    verify_derivative,
    verify_integral,
    verify_limit,
    verify_numeric,
    verify_equation,
    auto_verify,
    get_capabilities,
    parse_latex_expr,
    latex_to_python,
)

logger = logging.getLogger("ailearn.math_verifier_api")

router = APIRouter(prefix="/api/v1", tags=["math_verifier"])


# ============================================================
# 请求模型
# ============================================================

class DerivativeRequest(BaseModel):
    function: str = Field(..., description="原函数 LaTeX")
    derivative: str = Field(..., description="待验证的导数 LaTeX")
    var: str = Field("x", description="求导变量")


class IntegralRequest(BaseModel):
    function: str = Field(..., description="被积函数 LaTeX")
    integral: str = Field(..., description="待验证的积分结果 LaTeX")
    var: str = Field("x", description="积分变量")


class LimitRequest(BaseModel):
    function: str = Field(..., description="函数 LaTeX")
    limit_value: str = Field(..., description="待验证的极限值 LaTeX")
    var: str = Field("x", description="变量")
    point: str = Field("oo", description="极限点（oo=无穷大, 0, a 等）")


class NumericRequest(BaseModel):
    expression: str = Field(..., description="表达式 LaTeX")
    expected_value: float = Field(..., description="期望的数值答案")
    tolerance: float = Field(1e-4, description="容差")


class EquationRequest(BaseModel):
    equation: str = Field(..., description="方程 LaTeX（如 x^2-5x+6=0）")
    solution: str = Field(..., description="待验证的解 LaTeX")
    var: str = Field("x", description="变量")


class AutoVerifyRequest(BaseModel):
    question: str = Field(..., description="题目文本")
    answer: str = Field(..., description="待验证的答案")
    qtype: str = Field("short", description="题型")


class ParseRequest(BaseModel):
    latex: str = Field(..., description="LaTeX 表达式")


# ============================================================
# 端点
# ============================================================

@router.post("/math/verify/derivative")
async def verify_derivative_api(req: DerivativeRequest):
    """求导验证。"""
    result = verify_derivative(req.function, req.derivative, req.var)
    return result


@router.post("/math/verify/integral")
async def verify_integral_api(req: IntegralRequest):
    """积分验证。"""
    result = verify_integral(req.function, req.integral, req.var)
    return result


@router.post("/math/verify/limit")
async def verify_limit_api(req: LimitRequest):
    """极限验证。"""
    result = verify_limit(req.function, req.limit_value, req.var, req.point)
    return result


@router.post("/math/verify/numeric")
async def verify_numeric_api(req: NumericRequest):
    """数值验证。"""
    result = verify_numeric(req.expression, req.expected_value, req.tolerance)
    return result


@router.post("/math/verify/equation")
async def verify_equation_api(req: EquationRequest):
    """方程求解验证。"""
    result = verify_equation(req.equation, req.solution, req.var)
    return result


@router.post("/math/verify/auto")
async def auto_verify_api(req: AutoVerifyRequest):
    """自动识别题型并验证（有限支持，复杂题目需手动指定方法）。"""
    result = auto_verify(req.question, req.answer, req.qtype)
    return result


@router.get("/math/capabilities")
async def get_capabilities_api():
    """获取支持的验证能力列表。"""
    return get_capabilities()


@router.post("/math/parse")
async def parse_latex_api(req: ParseRequest):
    """测试 LaTeX 表达式解析（返回转换后的 Python 表达式和 sympy 结果）。"""
    py_str = latex_to_python(req.latex)
    expr = parse_latex_expr(req.latex)
    return {
        "latex": req.latex,
        "python_expr": py_str,
        "sympy_expr": str(expr) if expr is not None else None,
        "parse_success": expr is not None,
    }
