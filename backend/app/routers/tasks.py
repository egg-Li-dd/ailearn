"""后台任务路由：查询、取消、重试、删除。"""
from fastapi import APIRouter, HTTPException, Request

from ..schemas.task import (
    TaskCancelResponse,
    TaskEventOut,
    TaskListResponse,
    TaskOut,
    TaskRetryResponse,
)
from ..services import task_center

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
def list_tasks(
    request: Request,
    status: str | None = None,
    limit: int = 50,
):
    """任务列表（进行中优先，最近完成次之）。

    物理分库：App 端只看当前用户的任务；管理台通过 X-User-Key 切换查看指定用户。
    """
    user_key = getattr(request.state, "user_db_key", None)
    items = task_center.list_tasks(status=status, limit=limit, user_key=user_key)
    return {"items": items, "total": len(items)}


@router.get("/active", response_model=TaskListResponse)
def active_tasks(request: Request):
    """进行中的任务（running + pending）。

    物理分库：App 端只看当前用户的任务；管理台通过 X-User-Key 切换查看指定用户。
    """
    user_key = getattr(request.state, "user_db_key", None)
    all_items = task_center.list_tasks(limit=100, user_key=user_key)
    active = [t for t in all_items if t["status"] in ("running", "pending")]
    return {"items": active, "total": len(active)}


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str):
    """任务详情。"""
    task = task_center.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/{task_id}/events", response_model=list[TaskEventOut])
def get_task_events(task_id: str, limit: int = 200):
    """任务事件流水。"""
    task = task_center.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = task_center.get_task_events(task_id, limit=limit)
    return events


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
def cancel_task(task_id: str):
    """取消任务（协作式）。"""
    task = task_center.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    ok = task_center.cancel_task(task_id)
    if ok:
        return {"ok": True, "task_id": task_id, "message": "取消请求已发出"}
    return {"ok": False, "task_id": task_id, "message": "任务已结束，无法取消"}


@router.post("/{task_id}/retry", response_model=TaskRetryResponse)
async def retry_task(task_id: str):
    """重试失败任务。"""
    task = task_center.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    new_id = await task_center.retry_task(task_id)
    if new_id:
        return {"ok": True, "task_id": new_id, "message": "重试任务已创建"}
    return {"ok": False, "task_id": None, "message": "该任务类型不支持重试（未注册 runner）"}


@router.delete("/{task_id}")
def delete_task(task_id: str):
    """删除任务记录（仅已结束的任务）。"""
    task = task_center.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    ok = task_center.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="进行中的任务不允许删除，请先取消")
    return {"ok": True, "task_id": task_id}
