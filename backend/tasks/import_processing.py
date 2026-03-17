"""
本地导入处理任务
处理视频文件上传后的异步任务：字幕生成、缩略图生成、处理流程启动
"""

import logging
from pathlib import Path
from typing import Optional

from backend.core.database import get_db
from backend.services.project_service import ProjectService
from backend.utils.thumbnail_generator import generate_project_thumbnail

logger = logging.getLogger(__name__)


def run_import_task_sync(project_id: str, video_path: str, srt_file_path: Optional[str] = None):
    """
    同步入口，供 TaskManager 在线程池中调用。
    流程：生成缩略图 → 生成字幕 → 启动流水线
    """
    logger.info(f"[run_import_task_sync] 开始: {project_id}")
    db = next(get_db())
    project_service = ProjectService(db)

    try:
        # 1. 生成缩略图
        project = project_service.get(project_id)
        if project and not project.thumbnail:
            try:
                thumbnail_data = generate_project_thumbnail(project_id, Path(video_path))
                if thumbnail_data:
                    project.thumbnail = thumbnail_data
                    db.commit()
            except Exception as e:
                logger.error(f"缩略图生成失败（不影响后续流程）: {e}")

        # 2. 生成字幕（如果没有提供）
        srt_path = srt_file_path
        if not srt_path:
            try:
                from backend.utils.speech_recognizer import generate_subtitle_for_video
                project = project_service.get(project_id)
                video_category = "knowledge"
                if project and project.processing_config:
                    video_category = project.processing_config.get("video_category", "knowledge")
                model = "small" if video_category in ("business", "knowledge", "drama") else (
                    "medium" if video_category == "speech" else "base"
                )
                generated_subtitle = generate_subtitle_for_video(
                    Path(video_path), language="auto", model=model
                )
                srt_path = str(generated_subtitle)
                logger.info(f"字幕生成成功: {srt_path}")
            except Exception as e:
                logger.error(f"字幕生成失败: {e}")
                srt_path = None

        # 3. 启动流水线（通过 TaskManager 提交，确保与手动重试的 pipeline_{id} 任务去重）
        project_service.update_project_status(project_id, "processing")
        db.commit()
        from backend.tasks.processing import _run_pipeline_sync
        from backend.core.task_manager import task_manager
        import asyncio
        asyncio.run(task_manager.submit(
            f"pipeline_{project_id}",
            _run_pipeline_sync,
            project_id,
            video_path,
            srt_path,
        ))
        logger.info(f"[run_import_task_sync] 完成: {project_id}")

    except Exception as e:
        logger.error(f"[run_import_task_sync] 失败: {project_id} — {e}", exc_info=True)
        try:
            project_service.update_project_status(project_id, "failed")
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
