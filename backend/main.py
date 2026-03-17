"""FastAPI应用入口点"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 导入配置管理
from .core.config import settings, get_logging_config, get_api_key

# 配置日志
logging_config = get_logging_config()
logging.basicConfig(
    level=getattr(logging, logging_config["level"]),
    format=logging_config["format"],
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler(logging_config["file"])  # 输出到文件
    ]
)

logger = logging.getLogger(__name__)

# 使用统一的API路由注册
from .api.v1 import api_router
from .core.database import engine
from .models.base import Base

# Create FastAPI app
app = FastAPI(
    title="AutoClip API",
    description="AI视频切片处理API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Create database tables
@app.on_event("startup")
async def startup_event():
    logger.info("启动 AutoClip API 服务...")
    from .models.bilibili import BilibiliAccount, UploadRecord
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表创建完成")

    api_key = get_api_key()
    if api_key:
        import os
        os.environ["DASHSCOPE_API_KEY"] = api_key
        logger.info("API 密钥已加载")
    else:
        logger.warning("未找到 API 密钥配置")

    # 启动 asyncio 任务管理器（替代 Celery Worker）
    from .core.task_manager import task_manager  # noqa: F401
    logger.info("TaskManager 已就绪（asyncio 内置，无需外部 Worker）")

    # 启动定时任务调度器（替代 Celery beat）
    from .core.scheduler import start_scheduler
    start_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("正在关闭 AutoClip API 服务...")
    from .core.scheduler import stop_scheduler
    stop_scheduler()
    from .core.task_manager import task_manager
    await task_manager.shutdown()
    logger.info("AutoClip API 服务已关闭")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include unified API routes
app.include_router(api_router, prefix="/api/v1")

# 添加独立的video-categories端点
@app.get("/api/v1/video-categories")
async def get_video_categories():
    """获取视频分类配置."""
    return {
        "categories": [
            {
                "value": "default",
                "name": "默认",
                "description": "通用视频内容处理",
                "icon": "🎬",
                "color": "#4facfe"
            },
            {
                "value": "knowledge",
                "name": "知识科普",
                "description": "科学、技术、历史、文化等知识类内容",
                "icon": "📚",
                "color": "#52c41a"
            },
            {
                "value": "entertainment",
                "name": "娱乐",
                "description": "游戏、音乐、电影等娱乐内容",
                "icon": "🎮",
                "color": "#722ed1"
            },
            {
                "value": "business",
                "name": "商业",
                "description": "商业、创业、投资等商业内容",
                "icon": "💼",
                "color": "#fa8c16"
            },
            {
                "value": "experience",
                "name": "经验分享",
                "description": "个人经历、生活感悟等经验内容",
                "icon": "🌟",
                "color": "#eb2f96"
            },
            {
                "value": "opinion",
                "name": "观点评论",
                "description": "时事评论、观点分析等评论内容",
                "icon": "💭",
                "color": "#13c2c2"
            },
            {
                "value": "speech",
                "name": "演讲",
                "description": "公开演讲、讲座等演讲内容",
                "icon": "🎤",
                "color": "#f5222d"
            }
        ]
    }

# 导入统一错误处理中间件
from .core.error_middleware import global_exception_handler

# 注册全局异常处理器
app.add_exception_handler(Exception, global_exception_handler)

if __name__ == "__main__":
    import uvicorn
    import sys
    
    # 默认端口
    port = 8000
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    logger.error(f"无效的端口号: {sys.argv[i + 1]}")
                    port = 8000
    
    logger.info(f"启动服务器，端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)