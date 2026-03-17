"""处理服务（精简版）—— 仅保留真实被调用的方法"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.models.task import Task, TaskStatus, TaskType
from backend.repositories.task_repository import TaskRepository

logger = logging.getLogger(__name__)


class ProcessingService:
    """处理服务"""

    def __init__(self, db: Session):
        self.db = db
        self.task_repo = TaskRepository(db)

    # ─────────────────────────────────────────
    # 被 projects.py、enhanced_retry.py 调用
    # ─────────────────────────────────────────

    def _create_processing_task(
        self,
        project_id: str,
        task_type: TaskType = TaskType.VIDEO_PROCESSING,
    ) -> Task:
        """创建处理任务记录（审计用途）"""
        task_data = {
            "name": f"视频处理任务 - {project_id}",
            "description": f"处理项目 {project_id} 的视频内容",
            "project_id": project_id,
            "task_type": task_type,
            "status": TaskStatus.PENDING,
            "progress": 0.0,
            "metadata": {
                "project_id": project_id,
                "task_type": task_type.value if hasattr(task_type, "value") else task_type,
            },
        }
        return self.task_repo.create(**task_data)

    def get_processing_status(
        self,
        project_id: str,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取项目处理状态。
        从 Task 表读取最新任务状态（替代原来依赖 Redis 的实时进度）。
        """
        try:
            query = self.db.query(Task).filter(Task.project_id == project_id)
            if task_id:
                task = query.filter(Task.id == task_id).first()
            else:
                # 取最新任务
                task = query.order_by(Task.created_at.desc()).first()

            if not task:
                return {
                    "status": "pending",
                    "current_step": 0,
                    "total_steps": 6,
                    "step_name": "等待开始",
                    "progress": 0,
                    "error_message": None,
                }

            # 同时从 ProgressStore 获取实时进度（比 DB 更新鲜）
            realtime_percent = None
            realtime_message = None
            try:
                from backend.core.progress_store import progress_store
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
        except Exception as e:
            logger.error(f"[ProcessingService.get_processing_status] {e}")
            return {
                "status": "error",
                "current_step": 0,
                "total_steps": 6,
                "step_name": "状态查询失败",
                "progress": 0,
                "error_message": str(e),
            }

    def resume_processing(
        self,
        project_id: str,
        start_step: str,
        srt_path=None,
    ) -> Dict[str, Any]:
        """
        从指定步骤恢复处理（提交异步任务）。
        调用方（projects.py /resume 端点）在同步上下文中调用此方法，
        内部用 asyncio.get_event_loop().create_task 提交任务。
        """
        import asyncio
        from backend.core.task_manager import task_manager
        from backend.tasks.processing import _run_pipeline_sync
        from backend.models.project import Project, ProjectStatus
        from datetime import datetime

        try:
            # 定位视频文件
            from backend.core.config import get_data_directory
            raw = Path(get_data_directory()) / "projects" / project_id / "raw"
            video_path = str(raw / "input.mp4")

            if srt_path and not isinstance(srt_path, str):
                srt_path = str(srt_path)

            # 更新项目状态为 PROCESSING
            project = self.db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = ProjectStatus.PROCESSING
                project.updated_at = datetime.utcnow()
                self.db.commit()

            # 创建任务记录
            task = self._create_processing_task(project_id)
            task.status = TaskStatus.RUNNING
            self.db.commit()

            # 提交到 asyncio TaskManager
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass

            if loop and loop.is_running():
                loop.create_task(
                    task_manager.submit(
                        f"pipeline_{project_id}",
                        _run_pipeline_sync,
                        project_id,
                        video_path,
                        srt_path,
                    )
                )
            else:
                # 回退：在新线程中运行（不推荐，仅兜底）
                import threading
                threading.Thread(
                    target=lambda: _run_pipeline_sync(project_id, video_path, srt_path),
                    daemon=True,
                ).start()

            return {"success": True, "task_id": str(task.id), "start_step": start_step}

        except Exception as e:
            logger.error(f"[ProcessingService.resume_processing] {project_id} — {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def start_processing(
        self,
        project_id: str,
        srt_path=None,
    ) -> Dict[str, Any]:
        """
        开始处理（enhanced_retry.py 调用）。
        与 resume_processing 逻辑相同，从头开始（不指定 start_step）。
        """
        return self.resume_processing(project_id, start_step="step1_outline", srt_path=srt_path)

    # ─────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────

    def get_project_config(self, project_id: str) -> Dict[str, Any]:
        return {"project_id": project_id}

    def validate_project_setup(self, project_id: str) -> Dict[str, Any]:
        return {"valid": True, "message": "验证通过"}
