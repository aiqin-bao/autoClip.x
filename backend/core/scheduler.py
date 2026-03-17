"""
asyncio 定时任务调度器（替代 Celery beat）
在 FastAPI 进程内运行，无需外部调度进程。

注册的定时任务：
  - cleanup_expired_tasks：每天凌晨 2:00 清理 7 天前的已完成/失败任务
  - health_check_log：每 5 分钟写一条心跳日志
"""

import asyncio
import logging
from datetime import datetime, timedelta, time as dtime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# 任务函数
# ─────────────────────────────────────────────────────

def _cleanup_expired_tasks_sync(days: int = 7):
    """清理过期任务记录（同步，在线程池里执行）"""
    from backend.core.database import SessionLocal
    from backend.models.task import Task, TaskStatus

    db = SessionLocal()
    try:
        expired_time = datetime.utcnow() - timedelta(days=days)
        expired = db.query(Task).filter(
            Task.created_at < expired_time,
            Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED])
        ).all()

        count = 0
        for task in expired:
            try:
                db.delete(task)
                count += 1
            except Exception as e:
                logger.error(f"删除任务失败: {task.id} — {e}")

        db.commit()
        logger.info(f"[Scheduler] 过期任务清理完成，共 {count} 条")
    except Exception as e:
        logger.error(f"[Scheduler] cleanup_expired_tasks 失败: {e}")
        db.rollback()
    finally:
        db.close()


def _health_check_log():
    """打印心跳日志（同步）"""
    from backend.core.task_manager import task_manager
    from backend.core.progress_store import progress_store
    logger.info(
        f"[Scheduler] Heartbeat — running tasks: {task_manager.running_count()}, "
        f"tracked projects: {len(progress_store._snapshots)}"
    )


# ─────────────────────────────────────────────────────
# 调度器
# ─────────────────────────────────────────────────────

async def _wait_until(target: dtime):
    """等待到今天的 target 时刻（如果已过则等到明天）"""
    now = datetime.now()
    run_at = datetime.combine(now.date(), target)
    if run_at <= now:
        run_at += timedelta(days=1)
    await asyncio.sleep((run_at - datetime.now()).total_seconds())


async def _daily_at(target: dtime, func, *args, **kwargs):
    """每天在 target 时刻（本地时间）运行 func"""
    while True:
        await _wait_until(target)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            logger.error(f"[Scheduler] daily task failed: {e}")


async def _every(interval_secs: float, func, *args, **kwargs):
    """每隔 interval_secs 秒运行一次 func"""
    while True:
        await asyncio.sleep(interval_secs)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            logger.error(f"[Scheduler] periodic task failed: {e}")


_scheduler_tasks: list = []


def start_scheduler():
    """在 FastAPI startup 时调用，启动所有定时任务"""
    _scheduler_tasks.append(
        asyncio.create_task(
            _daily_at(dtime(hour=2, minute=0), _cleanup_expired_tasks_sync, 7),
            name="cleanup_expired_tasks",
        )
    )
    _scheduler_tasks.append(
        asyncio.create_task(
            _every(300, _health_check_log),  # 每 5 分钟
            name="health_check_log",
        )
    )
    logger.info("[Scheduler] 定时任务已启动（cleanup@02:00, heartbeat@5min）")


def stop_scheduler():
    """在 FastAPI shutdown 时调用"""
    for t in _scheduler_tasks:
        t.cancel()
    _scheduler_tasks.clear()
    logger.info("[Scheduler] 定时任务已停止")
