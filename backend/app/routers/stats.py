"""数据看板与设置 API。"""
import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_db
from ..models import UserSetting
from ..services import task_center
from ..services.call_logger import set_function_type
from ..services.ai_gateway import AiGatewayError, chat_once
from ..services.stats import heatmap, overview, radar

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/stats/overview")
def get_overview(db: Session = Depends(get_db)):
    return overview(db)


@router.get("/stats/radar")
def get_radar(db: Session = Depends(get_db)):
    return {"courses": radar(db)}


@router.get("/stats/heatmap")
def get_heatmap(days: int = 84, db: Session = Depends(get_db)):
    return {"days": days, "items": heatmap(db, days=min(365, max(28, days)))}


# ---------- 冲刺模式 ----------

SPRINT_KEY = "sprint_mode"


@router.get("/settings/sprint")
def get_sprint(db: Session = Depends(get_db)):
    row = db.get(UserSetting, SPRINT_KEY)
    return {"enabled": (row.value == "on") if row else False}


@router.put("/settings/sprint")
def put_sprint(payload: dict, db: Session = Depends(get_db)):
    enabled = bool(payload.get("enabled"))
    row = db.get(UserSetting, SPRINT_KEY)
    if row:
        row.value = "on" if enabled else "off"
    else:
        db.add(UserSetting(key=SPRINT_KEY, value="on" if enabled else "off"))
    db.commit()
    return {"enabled": enabled}


# ---------- 周报 ----------

WEEK_REPORT_PREFIX = "weekly_report."


@router.get("/stats/weekly-report")
def get_weekly_report(db: Session = Depends(get_db)):
    """最近一期周报（若有）。"""
    from sqlalchemy import select

    rows = list(
        db.scalars(
            select(UserSetting).where(UserSetting.key.like(f"{WEEK_REPORT_PREFIX}%"))
        )
    )
    if not rows:
        return {"exists": False}
    latest = max(rows, key=lambda r: r.key)
    return {"exists": True, "period": latest.key[len(WEEK_REPORT_PREFIX):], "content": latest.value}


async def _execute_weekly_report():
    """后台执行周报生成。"""
    db = SessionLocal()
    try:
        task_center.update_progress(stage="正在收集学习数据...", progress=20)
        ov = overview(db)
        rd = radar(db)
        courses_txt = ", ".join(f"{c['name']} {c['mastery']}" for c in rd)

        task_center.update_progress(stage="正在调用 AI 生成周报...", progress=50)
        try:
            set_function_type("stats")
            reply = await chat_once(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 ai学 的教练。基于用户本周学习数据生成一份周报，"
                            "500 字以内，风格认真直接。结构：\n"
                            "1. 本周概况（学习量、活跃度）\n"
                            "2. 科目强弱（引用掌握度数据，指出最薄弱一科）\n"
                            "3. 下周建议（具体 2-3 条，可执行）"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"本周数据：连续学习 {ov['streak_days']} 天，"
                            f"本周学习 {ov['week_minutes']} 分钟，累计完成任务 {ov['total_tasks_done']}。"
                            f"科目掌握度：{courses_txt}"
                        ),
                    },
                ],
                temperature=0.7,
            )
        except AiGatewayError as e:
            task_center.fail_task(error=f"AI 调用失败：{e}")
            return

        task_center.update_progress(stage="正在保存周报...", progress=90)
        today = date.today().isoformat()
        row = db.get(UserSetting, f"{WEEK_REPORT_PREFIX}{today}")
        if row:
            row.value = reply
        else:
            db.add(UserSetting(key=f"{WEEK_REPORT_PREFIX}{today}", value=reply))
        db.commit()

        task_center.complete_task(result={
            "period": today,
            "content_preview": reply[:200],
            "redirect": "/stats",
        })
    except Exception as e:
        task_center.fail_task(error=str(e))
    finally:
        db.close()


@router.post("/stats/weekly-report")
async def generate_weekly_report(db: Session = Depends(get_db)):
    """AI 生成本周学习周报（后台任务）。立即返回 task_id。"""
    task_id = task_center.create_task(
        task_type="weekly_report",
        title="生成学习周报",
    )
    token = task_center._current_task_id.set(task_id)
    try:
        task_center.mark_running(task_id)
        asyncio.create_task(_execute_weekly_report())
    finally:
        task_center._current_task_id.reset(token)
    return {"task_id": task_id, "status": "pending", "message": "周报生成任务已创建"}
