"""
内存进度存储 + SSE 广播（替代 Redis progress hset/publish）

用法：
  from backend.core.progress_store import progress_store
  progress_store.emit(project_id, "ANALYZE", "正在分析内容...", subpercent=50)

前端订阅：
  GET /api/v1/sse-progress/stream/{project_id}  → text/event-stream
"""

import json
import time
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 固定阶段定义（与 simple_progress.py 保持一致）
STAGES: List[Tuple[str, int]] = [
    ("INGEST",    10),
    ("SUBTITLE",  15),
    ("ANALYZE",   20),
    ("HIGHLIGHT", 25),
    ("EXPORT",    20),
    ("DONE",      10),
]
WEIGHTS = {name: w for name, w in STAGES}
ORDER   = [name for name, _ in STAGES]

STAGE_NAMES = {
    "INGEST":    "素材准备",
    "SUBTITLE":  "字幕处理",
    "ANALYZE":   "内容分析",
    "HIGHLIGHT": "片段定位",
    "EXPORT":    "视频导出",
    "DONE":      "处理完成",
}


def _compute_percent(stage: str, subpercent: Optional[float] = None) -> int:
    done = 0
    for s in ORDER:
        if s == stage:
            break
        done += WEIGHTS[s]
    cur = WEIGHTS.get(stage, 0)
    if subpercent is None:
        return min(100, done + cur) if stage == "DONE" else min(99, done)
    subpercent = max(0, min(100, subpercent))
    return min(99, done + int(cur * subpercent / 100))


class ProgressStore:
    """
    线程安全的内存进度存储。
    - 写入：emit()（可在任意线程调用）
    - 读取：get_snapshot()
    - SSE 订阅：subscribe() / unsubscribe()
    """

    def __init__(self):
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        # project_id -> list of asyncio.Queue
        self._sse_queues: Dict[str, List[asyncio.Queue]] = {}

    # ──────────────────────────────────────────────
    # 写入 API
    # ──────────────────────────────────────────────

    def emit(
        self,
        project_id: str,
        stage: str,
        message: str = "",
        subpercent: Optional[float] = None,
    ):
        """
        发布进度事件（线程安全，可在同步代码中调用）。
        内部会尝试将事件推送到所有活跃的 SSE 订阅队列。
        """
        percent = _compute_percent(stage, subpercent)
        payload = {
            "project_id": project_id,
            "stage": stage,
            "stage_name": STAGE_NAMES.get(stage, stage),
            "percent": percent,
            "message": message,
            "ts": int(time.time()),
        }
        self._snapshots[project_id] = payload
        logger.info(f"[Progress] {project_id} {stage}({percent}%) {message}")

        # 推送到 SSE 队列（在事件循环所在线程安全地放入）
        queues = self._sse_queues.get(project_id, [])
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
            except Exception:
                pass

    def clear(self, project_id: str):
        self._snapshots.pop(project_id, None)

    # ──────────────────────────────────────────────
    # 读取 API
    # ──────────────────────────────────────────────

    def get_snapshot(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._snapshots.get(project_id)

    def get_snapshots(self, project_ids: List[str]) -> List[Dict[str, Any]]:
        return [self._snapshots[pid] for pid in project_ids if pid in self._snapshots]

    # ──────────────────────────────────────────────
    # SSE 订阅 API
    # ──────────────────────────────────────────────

    def subscribe(self, project_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        if project_id not in self._sse_queues:
            self._sse_queues[project_id] = []
        self._sse_queues[project_id].append(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue):
        queues = self._sse_queues.get(project_id, [])
        if q in queues:
            queues.remove(q)
        if not queues:
            self._sse_queues.pop(project_id, None)


# 应用级单例
progress_store = ProgressStore()
