"""
SSE 进度推送端点（替代 simple_progress.py 的轮询方案）

GET /api/v1/sse-progress/stream/{project_id}
  → text/event-stream，实时推送 ProgressStore 事件

GET /api/v1/sse-progress/snapshot
  → 兼容旧轮询接口，一次性返回多个项目的进度快照
"""

import asyncio
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse, JSONResponse

from backend.core.progress_store import progress_store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stream/{project_id}")
async def stream_progress(project_id: str):
    """
    SSE 长连接：实时推送指定项目的进度事件。
    前端使用 EventSource('/api/v1/sse-progress/stream/{project_id}') 订阅。
    """
    async def event_generator():
        q = progress_store.subscribe(project_id)
        # 先发送当前快照（如果有），让前端立即同步状态
        snapshot = progress_store.get_snapshot(project_id)
        if snapshot:
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    # 处理完成后关闭连接
                    if payload.get("stage") in ("DONE", "ERROR"):
                        yield "event: done\ndata: {}\n\n"
                        break
                except asyncio.TimeoutError:
                    # 发送心跳，防止代理断开空闲连接
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            progress_store.unsubscribe(project_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/snapshot")
async def get_snapshot(project_ids: Optional[str] = Query(None)):
    """
    兼容旧轮询接口（simple_progress/snapshot）。
    前端传 project_ids=id1,id2,id3，返回各项目的最新进度快照。
    """
    if not project_ids:
        return JSONResponse(content=[])
    ids = [pid.strip() for pid in project_ids.split(",") if pid.strip()]
    results = progress_store.get_snapshots(ids)
    return JSONResponse(content=results)
