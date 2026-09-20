"""A/B 实验管理 API。

端点：
- GET    /api/v1/experiments              — 列出所有实验（支持 ?status= 过滤）
- GET    /api/v1/experiments/{id}         — 获取实验详情
- GET    /api/v1/experiments/{id}/stats   — 获取实验统计（按 variant 聚合）
- POST   /api/v1/experiments              — 创建实验
- PATCH  /api/v1/experiments/{id}         — 更新实验（状态、流量）
- DELETE /api/v1/experiments/{id}         — 删除实验
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.db import get_db, get_global_db
from ..models import AiExperiment, AiExperimentEvent
from ..services import experiment_service

logger = logging.getLogger("ailearn.experiment_api")
router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])

VALID_STATUSES = {"draft", "running", "paused", "ended"}


# ── 请求/响应模型 ──────────────────────────────────────────────

class VariantConfig(BaseModel):
    name: str = Field(..., description="变体名称，如 control/treatment")
    weight: int = Field(50, ge=1, le=100, description="权重（1-100）")


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="实验唯一名称")
    description: str = Field("", max_length=500, description="实验描述")
    variants: list[VariantConfig] = Field(..., min_length=2, description="变体配置列表")
    traffic_pct: int = Field(20, ge=0, le=100, description="流量百分比（0-100）")


class ExperimentUpdate(BaseModel):
    status: str | None = Field(None, description="实验状态：draft/running/paused/ended")
    traffic_pct: int | None = Field(None, ge=0, le=100, description="流量百分比（0-100）")
    description: str | None = Field(None, max_length=500, description="实验描述")


def _experiment_to_dict(exp: AiExperiment) -> dict:
    """将实验对象转为可序列化字典。"""
    try:
        variants = json.loads(exp.variants)
    except (json.JSONDecodeError, TypeError):
        variants = []
    return {
        "id": exp.id,
        "name": exp.name,
        "description": exp.description,
        "variants": variants,
        "traffic_pct": exp.traffic_pct,
        "status": exp.status,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else None,
    }


# ── 端点 ────────────────────────────────────────────────────────

@router.get("")
def list_experiments(status: str | None = None, db: Session = Depends(get_global_db)):
    """列出所有实验。

    可选 ?status=draft|running|paused|ended 过滤。
    """
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效状态：{status}，可选：{', '.join(sorted(VALID_STATUSES))}")
    exps = experiment_service.list_experiments(db, status=status)
    return {"experiments": [_experiment_to_dict(e) for e in exps], "total": len(exps)}


@router.get("/{experiment_id}")
def get_experiment(experiment_id: int, db: Session = Depends(get_global_db)):
    """获取实验详情。"""
    exp = db.get(AiExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail=f"实验 {experiment_id} 不存在")
    return _experiment_to_dict(exp)


@router.get("/{experiment_id}/stats")
def get_experiment_stats(experiment_id: int, db: Session = Depends(get_global_db)):
    """获取实验统计（按 variant 聚合）。

    返回每个 variant 的：调用次数、平均 token、平均成本、格式正确率、平均耗时。
    """
    exp = db.get(AiExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail=f"实验 {experiment_id} 不存在")
    stats = experiment_service.get_experiment_stats(db, experiment_id)
    return {
        "experiment_id": experiment_id,
        "experiment_name": exp.name,
        "status": exp.status,
        "stats": stats,
    }


@router.post("", status_code=201)
def create_experiment(req: ExperimentCreate, db: Session = Depends(get_global_db)):
    """创建新实验（默认 draft 状态，不影响生产流量）。"""
    # 检查名称唯一性
    existing = db.scalar(select(AiExperiment).where(AiExperiment.name == req.name))
    if existing:
        raise HTTPException(status_code=409, detail=f"实验名 '{req.name}' 已存在")

    variants = [v.model_dump() for v in req.variants]
    exp = experiment_service.create_experiment(
        db,
        name=req.name,
        description=req.description,
        variants=variants,
        traffic_pct=req.traffic_pct,
    )
    logger.info("创建实验：id=%s name=%s traffic=%s%%", exp.id, exp.name, exp.traffic_pct)
    return _experiment_to_dict(exp)


@router.patch("/{experiment_id}")
def update_experiment(experiment_id: int, req: ExperimentUpdate, db: Session = Depends(get_global_db)):
    """更新实验（状态、流量、描述）。

    修改状态或流量后会自动清除内存缓存，60 秒内生效。
    """
    exp = db.get(AiExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail=f"实验 {experiment_id} 不存在")

    updated = False

    if req.status is not None:
        if req.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"无效状态：{req.status}")
        exp.status = req.status
        updated = True
        logger.info("实验 %s 状态变更为 %s", exp.name, req.status)

    if req.traffic_pct is not None:
        exp.traffic_pct = max(0, min(100, req.traffic_pct))
        updated = True
        logger.info("实验 %s 流量变更为 %s%%", exp.name, exp.traffic_pct)

    if req.description is not None:
        exp.description = req.description
        updated = True

    if updated:
        db.commit()
        db.refresh(exp)
        experiment_service.invalidate_cache(exp.name)

    return _experiment_to_dict(exp)


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: int, db: Session = Depends(get_global_db)):
    """删除实验及其所有事件记录。

    警告：此操作不可逆，会同时删除该实验的所有统计数据。
    """
    exp = db.get(AiExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail=f"实验 {experiment_id} 不存在")

    # 先删除事件记录
    db.execute(delete(AiExperimentEvent).where(AiExperimentEvent.experiment_id == experiment_id))
    # 再删除实验
    db.delete(exp)
    db.commit()
    experiment_service.invalidate_cache(exp.name)
    logger.info("删除实验：id=%s name=%s（含事件记录）", experiment_id, exp.name)
    return None
