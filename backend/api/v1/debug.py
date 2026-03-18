"""
调试 API 接口
"""

import logging
from fastapi import APIRouter
from backend.core.progress_store import progress_store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/debug/progress/{project_id}")
async def debug_get_progress(project_id: str):
    """调试接口：获取项目当前进度快照"""
    snapshot = progress_store.get_snapshot(project_id)
    return {
        "success": True,
        "project_id": project_id,
        "snapshot": snapshot,
    }


@router.get("/debug/active-tasks")
async def debug_active_tasks():
    """调试接口：获取当前活跃任务列表"""
    from backend.core.task_manager import task_manager
    tasks = task_manager.list_tasks() if hasattr(task_manager, "list_tasks") else {}
    return {
        "success": True,
        "tasks": tasks,
    }
