"""
简化的进度服务 - 固定阶段 + 固定权重
内部改用 ProgressStore（内存），不依赖 Redis
"""

import logging
from typing import List, Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

STAGES: List[Tuple[str, int]] = [
    ("INGEST", 10),
    ("SUBTITLE", 15),
    ("ANALYZE", 20),
    ("HIGHLIGHT", 25),
    ("EXPORT", 20),
    ("DONE", 10),
]

WEIGHTS = {name: w for name, w in STAGES}
ORDER = [name for name, _ in STAGES]

STAGE_NAMES = {
    "INGEST": "素材准备",
    "SUBTITLE": "字幕处理",
    "ANALYZE": "内容分析",
    "HIGHLIGHT": "片段定位",
    "EXPORT": "视频导出",
    "DONE": "处理完成",
}


def compute_percent(stage: str, subpercent: Optional[float] = None) -> int:
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


def emit_progress(project_id: str, stage: str, message: str = "", subpercent: Optional[float] = None):
    from backend.core.progress_store import progress_store
    percent = compute_percent(stage, subpercent)
    progress_store.emit(project_id, stage=stage, percent=percent, message=message)
    logger.info(f"进度事件已发送: {project_id} - {stage} ({percent}%) - {message}")


def get_progress_snapshot(project_id: str) -> Optional[Dict[str, Any]]:
    from backend.core.progress_store import progress_store
    return progress_store.get_snapshot(project_id)


def get_multiple_progress_snapshots(project_ids: List[str]) -> List[Dict[str, Any]]:
    from backend.core.progress_store import progress_store
    return progress_store.get_snapshots(project_ids)


def clear_progress(project_id: str):
    from backend.core.progress_store import progress_store
    progress_store.clear(project_id)
    logger.info(f"已清除项目进度数据: {project_id}")


def get_stage_display_name(stage: str) -> str:
    return STAGE_NAMES.get(stage, stage)
