# -*- coding: utf-8 -*-
import asyncio
import sys

sys.path.insert(0, r"C:\creategame\AI学\backend")

from app.core.ai_config import require_ai_config
from app.services.ai_gateway import chat_once


async def main():
    try:
        cfg = require_ai_config()
        print("config ok:", cfg["base_url"], cfg["model"], "key_len", len(cfg["api_key"]))
        reply = await chat_once([{"role": "user", "content": "只回复两个字：正常"}], temperature=0.0)
        print("REPLY:", reply[:100])
    except Exception as e:
        import traceback

        traceback.print_exc()


asyncio.run(main())