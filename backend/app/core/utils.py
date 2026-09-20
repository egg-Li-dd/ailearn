"""通用路由工具：去重各模块中重复的辅助函数。"""
from fastapi import HTTPException
from sqlalchemy.orm import Session


def get_or_404(db: Session, model, obj_id: int, label: str = "资源"):
    """按主键获取对象，不存在则 404。"""
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return obj


def require_non_empty(value: str | None, field_label: str) -> str:
    """校验非空字符串，去除首尾空白。"""
    if value is None or not value.strip():
        raise HTTPException(status_code=422, detail=f"{field_label}不能为空")
    return value.strip()
