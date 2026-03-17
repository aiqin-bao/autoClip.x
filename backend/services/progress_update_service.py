"""进度更新服务存根（阶段二将替换为 ProgressStore + SSE）"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class _ProgressUpdateServiceStub:
    """兼容存根：原实现已删除，阶段二改为 SSE"""

    async def start_progress_monitoring(self, task_id: str):
        pass

    async def complete_task(self, task_id: str, **kwargs):
        pass

    def get_task_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        return None

    def get_all_active_tasks(self) -> list:
        return []


progress_update_service = _ProgressUpdateServiceStub()
