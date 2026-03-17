"""
任务进度查询API
提供实时任务进度查询功能
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any
from ...core.database import get_db
from ...models.task import Task, TaskStatus
from ...core.progress_store import progress_store
from ...core.task_manager import task_manager
from datetime import datetime

router = APIRouter()

@router.get("/task/{task_id}")
async def get_task_progress(task_id: str, db: Session = Depends(get_db)):
    """获取指定任务的进度"""
    try:
        # 从数据库获取任务信息
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # 从 ProgressStore 获取实时进度
        snapshot = progress_store.get_snapshot(str(task.project_id))

        response = {
            'id': task.id,
            'project_id': task.project_id,
            'name': task.name,
            'status': task.status,
            'progress': snapshot['percent'] if snapshot else task.progress,
            'current_step': task.current_step,
            'created_at': task.created_at.isoformat() if task.created_at else None,
            'started_at': task.started_at.isoformat() if task.started_at else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'updated_at': task.updated_at.isoformat() if task.updated_at else None,
        }

        if snapshot:
            response.update({
                'realtime_stage': snapshot.get('stage'),
                'realtime_message': snapshot.get('message'),
                'realtime_percent': snapshot.get('percent'),
            })

        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/project/{project_id}")
async def get_project_tasks_progress(project_id: str, db: Session = Depends(get_db)):
    """获取指定项目的所有任务进度"""
    try:
        # 获取项目的所有任务
        tasks = db.query(Task).filter(Task.project_id == project_id).all()
        
        tasks_progress = []
        for task in tasks:
            snapshot = progress_store.get_snapshot(str(task.project_id))

            task_info = {
                'id': task.id,
                'name': task.name,
                'status': task.status,
                'progress': snapshot['percent'] if snapshot else task.progress,
                'current_step': task.current_step,
                'created_at': task.created_at.isoformat() if task.created_at else None,
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                'updated_at': task.updated_at.isoformat() if task.updated_at else None,
            }

            if snapshot:
                task_info.update({
                    'realtime_stage': snapshot.get('stage'),
                    'realtime_message': snapshot.get('message'),
                    'realtime_percent': snapshot.get('percent'),
                })

            tasks_progress.append(task_info)
        
        return {
            'project_id': project_id,
            'tasks': tasks_progress,
            'total_tasks': len(tasks_progress),
            'running_tasks': len([t for t in tasks_progress if t['status'] == 'running']),
            'completed_tasks': len([t for t in tasks_progress if t['status'] == 'completed']),
            'failed_tasks': len([t for t in tasks_progress if t['status'] == 'failed'])
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/active")
async def get_active_tasks():
    """获取所有活动任务的进度（从 TaskManager 读取运行中任务）"""
    try:
        running_ids = list(task_manager._running_tasks.keys())
        snapshots = {}
        for tid in running_ids:
            # task_id 格式通常是 "pipeline_{project_id}"
            project_id = tid.replace("pipeline_", "", 1)
            snap = progress_store.get_snapshot(project_id)
            if snap:
                snapshots[tid] = snap

        formatted_tasks = [
            {
                'task_id': tid,
                'project_id': snap.get('project_id'),
                'stage': snap.get('stage'),
                'stage_name': snap.get('stage_name'),
                'percent': snap.get('percent'),
                'message': snap.get('message'),
            }
            for tid, snap in snapshots.items()
        ]

        return {
            'active_tasks': formatted_tasks,
            'total_active': task_manager.running_count(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/summary")
async def get_progress_summary(db: Session = Depends(get_db)):
    """获取进度摘要信息"""
    try:
        # 统计各种状态的任务数量
        total_tasks = db.query(Task).count()
        running_tasks = db.query(Task).filter(Task.status == TaskStatus.RUNNING).count()
        completed_tasks = db.query(Task).filter(Task.status == TaskStatus.COMPLETED).count()
        failed_tasks = db.query(Task).filter(Task.status == TaskStatus.FAILED).count()
        pending_tasks = db.query(Task).filter(Task.status == TaskStatus.PENDING).count()
        
        return {
            'summary': {
                'total_tasks': total_tasks,
                'running_tasks': running_tasks,
                'completed_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'pending_tasks': pending_tasks,
            },
            'active_tasks_count': task_manager.running_count(),
            'timestamp': datetime.utcnow().isoformat(),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
