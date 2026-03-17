"""通知任务（已去除 Celery 依赖）"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def send_processing_notification(
    project_id: str, task_id: str, message: str, notification_type: str = "info"
) -> Dict[str, Any]:
    notification_data = {
        "project_id": project_id,
        "task_id": task_id,
        "message": message,
        "type": notification_type,
        "timestamp": datetime.utcnow().isoformat(),
    }
    logger.info(f"通知: {notification_data}")
    return {"success": True, "notification": notification_data}


def send_error_notification(
    project_id: str, task_id: str, error_message: str,
    error_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    notification_data = {
        "project_id": project_id,
        "task_id": task_id,
        "type": "error",
        "message": error_message,
        "details": error_details,
        "timestamp": datetime.utcnow().isoformat(),
    }
    logger.error(f"错误通知: {notification_data}")
    return {"success": True, "notification": notification_data}


def send_completion_notification(
    project_id: str, task_id: str, result: Dict[str, Any]
) -> Dict[str, Any]:
    notification_data = {
        "project_id": project_id,
        "task_id": task_id,
        "type": "success",
        "message": "处理完成",
        "result": result,
        "timestamp": datetime.utcnow().isoformat(),
    }
    logger.info(f"完成通知: {notification_data}")
    return {"success": True, "notification": notification_data}
