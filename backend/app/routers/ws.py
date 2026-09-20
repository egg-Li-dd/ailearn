"""WebSocket 连接管理与推送。"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("ailearn.ws")
router = APIRouter()


class ConnectionManager:
    """单用户阶段：简单广播列表；多用户时升级为按用户路由。"""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("ws client connected, total=%d", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        if not self._clients:
            return
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(event)
            except Exception:  # 单条失败不影响其他
                await self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/api/v1/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 客户端心跳/忽略消息；断网时报错退出
            data = await websocket.receive_text()
            # 响应心跳：收到 ping 时回复 pong
            try:
                import json
                msg = json.loads(data)
                if msg.get('type') == 'ping':
                    await websocket.send_json({'type': 'pong'})
            except Exception:
                pass  # 非JSON消息忽略
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info("ws client disconnected, total=%d", len(manager._clients))
    except Exception:
        await manager.disconnect(websocket)
        logger.info("ws client error, total=%d", len(manager._clients))