"""
处理API路由（已修复：直接读 Task 表 + task_manager，不依赖不存在的 ProcessingService 方法）
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pathlib import Path

from ...core.database import get_db
from ...core.task_manager import task_manager
from ...models.task import Task, TaskStatus, TaskType
from ...models.project import Project, ProjectStatus

router = APIRouter()


@router.post("/projects/{project_id}/process")
async def process_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """开始处理项目"""
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if project.status.value not in ["pending", "failed"]:
            raise HTTPException(
                status_code=400, detail="Project is not in pending or failed status"
            )

        video_path = project.video_path
        if not video_path or not Path(video_path).exists():
            raise HTTPException(status_code=400, detail=f"Video file not found: {video_path}")

        srt_candidate = Path(video_path).parent / "input.srt"
        srt_path = str(srt_candidate) if srt_candidate.exists() else None

        from ...tasks.processing import _run_pipeline_sync

        await task_manager.submit(
            f"pipeline_{project_id}",
            _run_pipeline_sync,
            project_id,
            video_path,
            srt_path,
        )

        return {
            "message": "项目处理已开始",
            "project_id": project_id,
            "status": "processing",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/projects/{project_id}/processing-status")
async def get_processing_status(
    project_id: str,
    db: Session = Depends(get_db),
):
    """获取项目处理状态（从 Task 表和 ProgressStore 读取）"""
    try:
        task = (
            db.query(Task)
            .filter(Task.project_id == project_id)
            .order_by(Task.created_at.desc())
            .first()
        )

        if not task:
            return {
                "status": "pending",
                "current_step": 0,
                "total_steps": 6,
                "step_name": "等待开始",
                "progress": 0,
                "error_message": None,
            }

        # 从 ProgressStore 获取实时进度
        realtime_percent = None
        realtime_message = None
        try:
            from ...core.progress_store import progress_store
            snapshot = progress_store.get_snapshot(project_id)
            if snapshot:
                realtime_percent = snapshot.get("percent")
                realtime_message = snapshot.get("message")
        except Exception:
            pass

        return {
            "status": task.status.value if hasattr(task.status, "value") else task.status,
            "current_step": task.current_step or 0,
            "total_steps": task.total_steps or 6,
            "step_name": task.current_step or "处理中",
            "progress": realtime_percent if realtime_percent is not None else (task.progress or 0),
            "message": realtime_message,
            "error_message": task.error_message,
            "task_id": str(task.id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.post("/projects/{project_id}/process/step/{step_number}")
async def process_step(
    project_id: str,
    step_number: int,
    db: Session = Depends(get_db),
):
    """处理单个步骤（提交完整流水线，由 pipeline_adapter 内部跳过已完成步骤）"""
    if step_number < 1 or step_number > 6:
        raise HTTPException(status_code=400, detail="步骤编号必须在1-6之间")

    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        video_path = project.video_path
        if not video_path or not Path(video_path).exists():
            raise HTTPException(status_code=400, detail=f"Video file not found: {video_path}")

        srt_candidate = Path(video_path).parent / "input.srt"
        srt_path = str(srt_candidate) if srt_candidate.exists() else None

        from ...tasks.processing import _run_pipeline_sync

        await task_manager.submit(
            f"pipeline_{project_id}",
            _run_pipeline_sync,
            project_id,
            video_path,
            srt_path,
        )

        return {
            "message": f"步骤 {step_number} 处理任务已提交",
            "project_id": project_id,
            "step": step_number,
            "status": "processing",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"步骤处理失败: {str(e)}")