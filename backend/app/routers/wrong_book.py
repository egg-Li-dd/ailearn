"""错题本 API（Phase 5）。

端点：
- GET  /api/v1/wrong-book/list        错题列表
- GET  /api/v1/wrong-book/stats       错题统计
- GET  /api/v1/wrong-book/recommend   针对性复习推荐
- POST /api/v1/wrong-book/practice    生成错题重练
- GET  /api/v1/wrong-book/export      导出错题本
"""
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..services.wrong_book import (
    get_wrong_answers,
    get_wrong_stats,
    get_review_recommendations,
    generate_practice,
    export_wrong_book,
)

logger = logging.getLogger("ailearn.wrong_book_api")

router = APIRouter(prefix="/api/v1", tags=["wrong_book"])


# ============================================================
# 请求模型
# ============================================================

class PracticeRequest(BaseModel):
    subject_id: int | None = Field(None, description="按科目筛选")
    node_id: int | None = Field(None, description="按知识点筛选")
    count: int = Field(5, ge=1, le=50, description="题目数量（1-50）")
    mode: str = Field("random", description="出题模式：random/frequent/recent")


# ============================================================
# 端点
# ============================================================

@router.get("/wrong-book/list")
async def wrong_book_list(
    subject_id: int | None = Query(None, description="按科目筛选"),
    node_id: int | None = Query(None, description="按知识点筛选"),
    days: int | None = Query(None, description="只看最近N天的错题"),
    min_wrong_count: int = Query(1, ge=1, description="最低错误次数"),
    db: Session = Depends(get_db),
):
    """获取错题列表（按题目去重，记录错误次数）。"""
    wrong_list = get_wrong_answers(
        db,
        subject_id=subject_id,
        node_id=node_id,
        days=days,
        min_wrong_count=min_wrong_count,
    )
    return {
        "total": len(wrong_list),
        "wrong_questions": wrong_list,
    }


@router.get("/wrong-book/stats")
async def wrong_book_stats(
    subject_id: int | None = Query(None, description="按科目筛选"),
    days: int | None = Query(None, description="只看最近N天"),
    db: Session = Depends(get_db),
):
    """获取错题统计数据（总数、高频错题、薄弱知识点、趋势）。"""
    stats = get_wrong_stats(db, subject_id=subject_id, days=days)
    return stats


@router.get("/wrong-book/recommend")
async def wrong_book_recommend(
    subject_id: int | None = Query(None, description="按科目筛选"),
    limit: int = Query(10, ge=1, le=20, description="推荐数量上限"),
    db: Session = Depends(get_db),
):
    """获取针对性复习推荐（优先知识点+最近错题+高频错题+复习计划）。"""
    recommendations = get_review_recommendations(db, subject_id=subject_id, limit=limit)
    return recommendations


@router.post("/wrong-book/practice")
async def wrong_book_practice(
    req: PracticeRequest,
    db: Session = Depends(get_db),
):
    """生成错题重练题目（随机/高频/最近模式）。"""
    if req.mode not in ("random", "frequent", "recent"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"无效的出题模式: {req.mode}，可选: random/frequent/recent")

    result = generate_practice(
        db,
        subject_id=req.subject_id,
        node_id=req.node_id,
        count=req.count,
        mode=req.mode,
    )
    return result


@router.get("/wrong-book/export")
async def wrong_book_export(
    subject_id: int | None = Query(None, description="按科目筛选"),
    format: str = Query("csv", description="导出格式：csv/json"),
    db: Session = Depends(get_db),
):
    """导出错题本（CSV/JSON，直接下载）。"""
    if format not in ("csv", "json"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"无效的导出格式: {format}，可选: csv/json")

    result = export_wrong_book(db, subject_id=subject_id, format=format)

    # 对文件名进行 URL 编码，避免 Content-Disposition 头部 latin-1 编码错误
    from urllib.parse import quote
    encoded_filename = quote(result["filename"])

    # 设置响应头让浏览器下载
    if format == "csv":
        # 加 BOM 让 Excel 正确识别中文，用 UTF-8 字节返回
        content_bytes = ("\ufeff" + result["content"]).encode("utf-8")
        media_type = "text/csv; charset=utf-8"
    else:
        content_bytes = result["content"].encode("utf-8")
        media_type = "application/json; charset=utf-8"

    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )
