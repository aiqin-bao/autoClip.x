"""
asyncio 任务管理器（替代 Celery Worker）
- 在 FastAPI 进程内直接运行后台任务，无需外部 Worker 进程
- 用 asyncio.Semaphore 控制最大并发数（默认 2）
- CPU 密集型任务（ffmpeg/Whisper）在 ThreadPoolExecutor 里运行
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_TASKS = 2
_THREAD_POOL_WORKERS = 4


class TaskManager:
    """应用级单例任务管理器"""

    def __init__(self, max_concurrent: int = _MAX_CONCURRENT_TASKS):
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._executor = ThreadPoolExecutor(max_workers=_THREAD_POOL_WORKERS, thread_name_prefix="autoclip")
        self._max_concurrent = max_concurrent
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    async def submit(
        self,
        task_id: str,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        提交一个后台任务。
        - func 若是同步函数，会在线程池里运行（不阻塞事件循环）
        - func 若是异步函数，直接 await
        """
        async def _run():
            async with self._get_semaphore():
                logger.info(f"[TaskManager] 开始任务: {task_id}")
                try:
                    loop = asyncio.get_running_loop()
                    if asyncio.iscoroutinefunction(func):
                        await func(*args, **kwargs)
                    else:
                        await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))
                    logger.info(f"[TaskManager] 任务完成: {task_id}")
                except Exception as e:
                    logger.error(f"[TaskManager] 任务失败: {task_id} — {e}", exc_info=True)
                finally:
                    with self._lock:
                        self._running_tasks.pop(task_id, None)

        task = asyncio.create_task(_run(), name=task_id)
        with self._lock:
            self._running_tasks[task_id] = task

    def running_count(self) -> int:
        return len(self._running_tasks)

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running_tasks

    async def shutdown(self):
        """优雅关闭：等待所有任务结束"""
        tasks = list(self._running_tasks.values())
        if tasks:
            logger.info(f"[TaskManager] 等待 {len(tasks)} 个任务结束...")
            await asyncio.gather(*tasks, return_exceptions=True)
        self._executor.shutdown(wait=True)
        logger.info("[TaskManager] 已关闭")


# 应用级单例
task_manager = TaskManager()
