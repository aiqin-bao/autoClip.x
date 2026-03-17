"""
简化的进度 API（兼容旧轮询接口）
内部改用 ProgressStore（内存），不再依赖 Redis
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import logging

from backend.core.progress_store import progress_store, STAGES, STAGE_NAMES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simple-progress", tags=["simple-progress"])


@router.get("/snapshot")
def get_progress_snapshots(project_ids: List[str] = Query(..., description="项目ID列表")):
    """批量获取项目进度快照"""
    try:
        if not project_ids:
            return []
        snapshots = progress_store.get_snapshots(project_ids)
        return snapshots
    except Exception as e:
        logger.error(f"获取进度快照失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取进度快照失败: {str(e)}")


@router.get("/snapshot/{project_id}")
def get_single_progress_snapshot(project_id: str):
    """获取单个项目进度快照"""
    try:
        snapshot = progress_store.get_snapshot(project_id)
        if snapshot is None:
            return {
                "project_id": project_id,
                "stage": "INGEST",
                "percent": 0,
                "message": "等待开始",
                "ts": 0,
            }
        return snapshot
    except Exception as e:
        logger.error(f"获取项目进度快照失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取项目进度快照失败: {str(e)}")


@router.get("/stages")
def get_available_stages():
    """获取可用的处理阶段信息"""
    stages_info = [
        {"stage": s, "weight": w, "display_name": STAGE_NAMES.get(s, s)}
        for s, w in STAGES
    ]
    return {
        "stages": stages_info,
        "total_weight": sum(w for _, w in STAGES),
    }
