"""视频处理任务（asyncio TaskManager 版本，已去除 Celery 依赖）"""

import asyncio
import logging
from typing import Optional
from datetime import datetime

from backend.core.database import SessionLocal
from backend.models.project import Project, ProjectStatus
from backend.models.task import Task, TaskStatus, TaskType

logger = logging.getLogger(__name__)


def _run_pipeline_sync(
    project_id: str,
    input_video_path: Optional[str],
    input_srt_path: Optional[str],
):
    """
    同步入口，供 TaskManager 在线程池中调用。
    等价于原来的 process_video_pipeline.delay()。

    状态更新优先由 simple_pipeline_adapter 内的 data_sync_service 完成；
    此处只在 data_sync_service 执行前后做兜底保护。
    """
    logger.info(f"[_run_pipeline_sync] 开始: {project_id}")
    db = SessionLocal()
    task_id = None
    try:
        # 记录任务（审计用途，不用于状态驱动）
        task = Task(
            name="视频处理流水线",
            description=f"处理项目 {project_id}",
            task_type=TaskType.VIDEO_PROCESSING,
            project_id=project_id,
            status=TaskStatus.RUNNING,
            progress=0,
            current_step="初始化",
            total_steps=6,
        )
        db.add(task)
        db.commit()
        task_id = str(task.id)

        # 定位视频和字幕文件
        if not input_video_path:
            from backend.core.config import get_data_directory
            from pathlib import Path
            raw = Path(get_data_directory()) / "projects" / project_id / "raw"
            input_video_path = str(raw / "input.mp4")
            if not input_srt_path:
                srt_candidate = raw / "input.srt"
                input_srt_path = str(srt_candidate) if srt_candidate.exists() else None

        from backend.services.simple_pipeline_adapter import create_simple_pipeline_adapter
        pipeline = create_simple_pipeline_adapter(project_id, task_id)
        result = asyncio.run(pipeline.process_project_sync(input_video_path, input_srt_path))

        # pipeline 内 data_sync_service 已设置 project.status = COMPLETED
        # 这里仅更新 task 状态
        failed = result.get("status") == "failed"
        task.status = TaskStatus.FAILED if failed else TaskStatus.COMPLETED
        task.progress = 0 if failed else 100
        task.current_step = "处理失败" if failed else "处理完成"
        if failed:
            task.error_message = result.get("message", "处理失败")
        db.commit()

        # 如果 pipeline 报告失败（data_sync_service 可能未设 FAILED），做兜底
        if failed:
            _force_project_status(project_id, ProjectStatus.FAILED)

        logger.info(f"[_run_pipeline_sync] 完成: {project_id}")

    except Exception as e:
        logger.error(f"[_run_pipeline_sync] 异常: {project_id} — {e}", exc_info=True)
        # 任务状态设为 FAILED
        if task_id:
            try:
                t = db.query(Task).filter(Task.id == task_id).first()
                if t:
                    t.status = TaskStatus.FAILED
                    t.error_message = str(e)
                    db.commit()
            except Exception:
                pass
        # 项目状态兜底（仅当 data_sync_service 未能更新时）
        _force_project_status(project_id, ProjectStatus.FAILED)
        raise
    finally:
        db.close()


def _force_project_status(project_id: str, status: ProjectStatus):
    """
    用独立 session 强制设置项目状态（兜底用，避免主 session 事务问题）。
    """
    db2 = SessionLocal()
    try:
        project = db2.query(Project).filter(Project.id == project_id).first()
        if project and project.status != status:
            project.status = status
            project.updated_at = datetime.utcnow()
            if status == ProjectStatus.COMPLETED:
                project.completed_at = datetime.utcnow()
            db2.commit()
            logger.info(f"[_force_project_status] {project_id} → {status}")
    except Exception as e2:
        logger.error(f"[_force_project_status] 更新失败: {e2}")
        db2.rollback()
    finally:
        db2.close()
