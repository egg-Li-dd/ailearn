# -*- coding: utf-8 -*-
import asyncio
import json
import sys

sys.path.insert(0, r"C:\creategame\AI学\backend")

from app.core.db import SessionLocal
from sqlalchemy import select
from app.models import Course
from app.routers.ai_action import ai_generate, GenerateRequest, _extract_json


async def main():
    db = SessionLocal()
    payload = GenerateRequest(
        context_type="schedule_item",
        items=[],
        instruction="每周二上午9点英语一、周五晚7点半数据结构各一节课",
    )
    try:
        result = await ai_generate(payload, db)
        print("OK:", json.dumps(result, ensure_ascii=False)[:600])
    except Exception as e:
        import traceback

        traceback.print_exc()
    finally:
        db.close()


asyncio.run(main())