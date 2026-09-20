"""复习队列 API。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..services.review import due_items, rate_item


class ReviewCompleteRequest(BaseModel):
    correct: bool


class ReviewRateRequest(BaseModel):
    rating: int = Field(ge=0, le=3, description="0 重做 / 1 模糊 / 2 记得 / 3 清楚")


router = APIRouter(prefix="/api/v1/review", tags=["review"])


@router.get("/today")
def today(db: Session = Depends(get_db)):
    return due_items(db)


@router.post("/{queue_id}/rate")
def rate(
    queue_id: int,
    payload: ReviewRateRequest,
    db: Session = Depends(get_db),
):
    """FSRS 四档评分；返回新卡片状态（下次复习时间/档位预览）。"""
    try:
        return rate_item(db, queue_id, rating=payload.rating)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{queue_id}/complete")
def complete(
    queue_id: int,
    payload: ReviewCompleteRequest,
    db: Session = Depends(get_db),
):
    """兼容旧 App（对/错布尔）：正确→记得(2)，错误→重做(0)。"""
    try:
        return rate_item(db, queue_id, rating=2 if payload.correct else 0)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
