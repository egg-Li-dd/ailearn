"""手写答案批改 API。

端点：
- POST /api/v1/handwrite/grade — 上传手写答案图片（base64）+ 题目信息，返回批改结果
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..services.ai_gateway import AiGatewayError
from ..services.handwrite_grading import grade_handwrite

logger = logging.getLogger("ailearn.handwrite_api")
router = APIRouter(prefix="/api/v1/handwrite", tags=["handwrite"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB（base64 后约 13MB）


class PointItem(BaseModel):
    point: str = Field(..., description="得分点描述")
    score: int = Field(1, ge=1, description="该得分点分值")


class GradeRequest(BaseModel):
    question: str = Field(..., description="题目题干")
    reference_answer: str = Field(..., description="参考答案")
    image_base64: str = Field(..., description="手写答案图片 base64（可含 data:image/...;base64, 前缀）")
    points: list[PointItem] | None = Field(None, description="得分点列表")
    max_points: int = Field(10, ge=1, description="满分（无得分点时使用）")
    model: str | None = Field(None, description="多模态模型名，默认 qwen-vl-max")


@router.post("/grade")
async def grade_handwrite_answer(req: GradeRequest, db: Session = Depends(get_db)):
    """批改手写答案。

    接收题目信息 + 手写答案图片（base64），调用多模态 AI 识别手写并逐得分点评分。
    返回结构化批改结果（识别文本、得分点明细、错误分析、解析）。
    """
    # 校验图片大小（base64 解码后估算）
    try:
        import base64 as b64
        pure = req.image_base64.split(",", 1)[1] if "," in req.image_base64 else req.image_base64
        img_bytes = len(b64.b64decode(pure))
        if img_bytes > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"图片过大（{img_bytes // 1024}KB，上限 {MAX_IMAGE_BYTES // 1024 // 1024}MB）",
            )
    except Exception:
        # base64 校验失败交给服务层处理
        pass

    points = [p.model_dump() for p in req.points] if req.points else None

    try:
        result = await grade_handwrite(
            question=req.question,
            reference_answer=req.reference_answer,
            image_base64=req.image_base64,
            points=points,
            max_points=req.max_points,
            model=req.model,
            db=db,
        )
    except AiGatewayError as e:
        logger.error("手写批改 AI 调用失败: %s", e)
        raise HTTPException(status_code=502, detail=f"AI 批改服务调用失败: {e}") from e
    except ValueError as e:
        logger.error("手写批改参数错误: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    return result


@router.get("/status")
def handwrite_status():
    """检查手写批改服务状态。"""
    from ..services.handwrite_grading import DEFAULT_VISION_MODEL
    return {
        "available": True,
        "default_model": DEFAULT_VISION_MODEL,
        "max_image_mb": MAX_IMAGE_BYTES // 1024 // 1024,
    }
