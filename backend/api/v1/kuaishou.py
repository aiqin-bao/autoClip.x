"""
快手视频导入 API
支持从快手分享链接中解析视频信息，下载并启动切片流水线
"""

import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Form
from pydantic import BaseModel

from ...utils.kuaishou_downloader import (
    KuaishouDownloader,
    extract_kuaishou_url,
    is_kuaishou_url,
    get_kuaishou_video_info,
)
from ...core.config import get_data_directory

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存中的下载任务状态
download_tasks: dict = {}


# ---------- Pydantic 模型 ----------

class KuaishouParseRequest(BaseModel):
    share_text: str  # 可以是完整分享文本或纯链接


class KuaishouDownloadRequest(BaseModel):
    share_text: str
    project_name: str
    video_category: Optional[str] = "default"


class KuaishouDownloadTask(BaseModel):
    id: str
    url: str
    project_name: str
    video_category: str
    status: str
    progress: float
    error_message: Optional[str] = None
    project_id: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- 辅助函数 ----------

def _parse_url_from_text(share_text: str) -> str:
    """从分享文本中提取链接"""
    url = extract_kuaishou_url(share_text)
    if url:
        return url
    stripped = share_text.strip()
    if is_kuaishou_url(stripped):
        return stripped
    raise ValueError(
        "无法从文本中识别快手链接，请确保包含 www.kuaishou.com 的链接"
    )


async def _update_project_progress(project_id: str, progress: float, message: str):
    """更新项目下载进度"""
    try:
        from ...core.database import SessionLocal
        from ...services.project_service import ProjectService

        db = SessionLocal()
        try:
            project_service = ProjectService(db)
            project = project_service.get(project_id)
            if project:
                if not project.processing_config:
                    project.processing_config = {}
                project.processing_config.update({
                    "download_progress": progress,
                    "download_message": message,
                })
                if progress >= 100.0:
                    from ...schemas.project import ProjectStatus
                    project.status = ProjectStatus.PENDING
                db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error(f"更新项目下载进度失败: {e}")


# ---------- 下载任务处理 ----------

async def _process_download(task_id: str, url: str, request: KuaishouDownloadRequest, project_id: str):
    """后台下载并处理快手视频（混合方案）"""
    try:
        download_tasks[task_id].status = "processing"
        download_tasks[task_id].progress = 10.0
        await _update_project_progress(project_id, 10.0, "正在连接快手服务器...")

        # 下载视频
        data_dir = get_data_directory()
        download_dir = data_dir / "temp"
        download_dir.mkdir(exist_ok=True)

        video_path = ""
        subtitle_path = None
        download_method = ""

        async def progress_cb(msg: str, pct: float):
            download_tasks[task_id].progress = max(10.0, min(pct, 85.0))
            await _update_project_progress(project_id, download_tasks[task_id].progress, msg)

        # ── 方案 1：videodl（推荐，多个解析器自动切换）─────────────
        try:
            from ...utils.kuaishou_videodl import download_kuaishou_video_videodl
            logger.info("尝试使用 videodl 下载快手视频...")
            await progress_cb("使用 videodl 下载...", 15)
            
            video_path = await download_kuaishou_video_videodl(
                url, 
                download_dir, 
                progress_callback=progress_cb
            )
            download_method = "videodl"
            logger.info(f"✓ videodl 下载成功: {video_path}")
            
        except Exception as vdl_err:
            logger.warning(f"✗ videodl 下载失败: {str(vdl_err)[:200]}")
            
            # ── 方案 2：Playwright（备选）─────────────────────────
            try:
                from ...utils.kuaishou_playwright import KuaishouPlaywrightExtractor
                logger.info("回退到 Playwright 下载...")
                await progress_cb("使用 Playwright 下载...", 20)
                
                loop = asyncio.get_running_loop()
                extractor = KuaishouPlaywrightExtractor(headless=True)
                
                def progress_cb_sync(msg: str, pct: float):
                    download_tasks[task_id].progress = max(10.0, min(pct, 85.0))
                
                video_path = await loop.run_in_executor(
                    None,
                    extractor.download_video_sync,
                    url,
                    download_dir,
                    progress_cb_sync,
                )
                download_method = "playwright"
                logger.info(f"✓ Playwright 下载成功: {video_path}")
                
            except Exception as pw_err:
                logger.error(f"✗ Playwright 下载失败: {str(pw_err)[:200]}")
                raise RuntimeError(
                    f"所有下载方案均失败\n"
                    f"- videodl: {str(vdl_err)[:100]}\n"
                    f"- Playwright: {str(pw_err)[:100]}\n\n"
                    f"建议：\n"
                    f"1. 使用 B站/YouTube（更稳定）\n"
                    f"2. 手动下载后通过'文件导入'上传"
                )

        await _update_project_progress(
            project_id, 60.0, 
            f"视频下载完成（使用 {download_method}），正在生成字幕..."
        )

        # 用 Whisper 生成字幕
        if video_path and not subtitle_path:
            logger.info("快手视频无外挂字幕，启动 Whisper ASR...")
            await _update_project_progress(project_id, 70.0, "正在使用 Whisper 识别字幕...")
            try:
                from ...utils.speech_recognizer import generate_subtitle_for_video
                from pathlib import Path
                generated = generate_subtitle_for_video(
                    Path(video_path),
                    language="auto",
                    model="base",
                )
                subtitle_path = str(generated)
                logger.info(f"Whisper 字幕生成成功: {subtitle_path}")
                await _update_project_progress(project_id, 88.0, "字幕生成完成，整理文件中...")
            except Exception as e:
                logger.error(f"Whisper 字幕生成失败: {e}")
                subtitle_path = None

        download_tasks[task_id].progress = 85.0

        # 移动文件到项目目录
        from ...core.database import SessionLocal
        from ...services.project_service import ProjectService

        db = SessionLocal()
        try:
            project_service = ProjectService(db)
            project = project_service.get(project_id)
            if not project:
                raise RuntimeError(f"项目 {project_id} 不存在")

            from ...core.path_utils import get_project_directory
            import shutil
            from pathlib import Path

            project_dir = get_project_directory(project_id)
            raw_dir = project_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)

            if video_path:
                vp = Path(video_path)
                if vp.exists():
                    dest = raw_dir / "input.mp4"
                    shutil.move(str(vp), str(dest))
                    project.video_path = str(dest)
                    logger.info(f"视频文件已移动: {dest}")

            if subtitle_path:
                sp = Path(subtitle_path)
                if sp.exists():
                    dest_srt = raw_dir / "input.srt"
                    shutil.move(str(sp), str(dest_srt))
                    if not project.processing_config:
                        project.processing_config = {}
                    project.processing_config["subtitle_path"] = str(dest_srt)
                    logger.info(f"字幕文件已移动: {dest_srt}")

            if not project.processing_config:
                project.processing_config = {}
            project.processing_config.update({
                "download_status": "completed",
                "download_progress": 100.0,
            })
            db.commit()

            # 检查字幕是否就位
            srt_file = raw_dir / "input.srt"
            if not srt_file.exists():
                logger.error("字幕文件不存在，标记项目失败")
                from ...schemas.project import ProjectStatus
                project.status = ProjectStatus.FAILED
                project.processing_config["error_message"] = "字幕生成失败，请尝试其他 ASR 方式"
                db.commit()
                download_tasks[task_id].status = "failed"
                download_tasks[task_id].error_message = "字幕生成失败"
                download_tasks[task_id].progress = 0.0
                await _update_project_progress(project_id, 0.0, "下载失败：字幕生成失败")
                return

            await _update_project_progress(project_id, 100.0, "下载完成，准备开始处理")

            download_tasks[task_id].status = "completed"
            download_tasks[task_id].progress = 100.0
            download_tasks[task_id].project_id = project_id
            download_tasks[task_id].updated_at = datetime.now().isoformat()

            # 启动自动化流水线
            try:
                from ...schemas.project import ProjectStatus
                project.status = ProjectStatus.PENDING
                db.commit()
                from ...services.auto_pipeline_service import auto_pipeline_service
                loop = asyncio.get_running_loop()
                await loop.create_task(auto_pipeline_service.auto_start_pipeline(project_id))
                logger.info(f"快手项目 {project_id} 流水线已启动")
            except Exception as e:
                logger.error(f"启动流水线失败: {e}")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"快手下载任务失败 [{task_id}]: {e}")
        if task_id in download_tasks:
            download_tasks[task_id].status = "failed"
            download_tasks[task_id].error_message = str(e)
            download_tasks[task_id].updated_at = datetime.now().isoformat()
        await _update_project_progress(project_id, 0.0, f"下载失败: {e}")


# ---------- API 路由 ----------

@router.post("/parse")
async def parse_kuaishou_video(share_text: str = Form(...)):
    """
    解析快手视频信息。
    
    使用混合方案：
    1. 优先使用 videodl（多个通用解析器）
    2. 失败后尝试 Playwright
    3. 都失败则提示用户使用替代方案
    """
    try:
        url = _parse_url_from_text(share_text)
        logger.info(f"解析快手视频: {url}")

        # 方案 1：videodl（推荐，多个解析器自动切换）
        try:
            from ...utils.kuaishou_videodl import get_kuaishou_video_info_videodl
            info = await get_kuaishou_video_info_videodl(url)
            
            parser_used = info.get('parser_used', 'videodl')
            logger.info(f"✓ videodl 解析成功（使用 {parser_used}）: {info.get('title')}")
            
            return {
                "success": True,
                "extracted_url": url,
                "method": f"videodl ({parser_used})",
                "video_info": {
                    "title": info.get("title", "快手视频"),
                    "description": info.get("title", ""),
                    "duration": int(info.get("duration", 0)),
                    "uploader": info.get("uploader", "快手用户"),
                    "upload_date": "",
                    "view_count": info.get("view_count", 0),
                    "like_count": info.get("like_count", 0),
                    "thumbnail": info.get("thumbnail_url", ""),
                },
            }
        except Exception as vdl_err:
            logger.warning(f"✗ videodl 解析失败: {str(vdl_err)[:200]}")
            
            # 方案 2：Playwright（备选）
            try:
                from ...utils.kuaishou_playwright import get_kuaishou_video_info_playwright
                info = await get_kuaishou_video_info_playwright(url)
                
                if not info.get('video_url'):
                    logger.warning(f"Playwright 未能获取视频下载地址")
                    raise RuntimeError("未能获取视频下载地址")
                
                logger.info(f"✓ Playwright 解析成功: {info.get('title')}")
                return {
                    "success": True,
                    "extracted_url": url,
                    "method": "playwright",
                    "video_info": {
                        "title": info.get("title", "快手视频"),
                        "description": info.get("title", ""),
                        "duration": int(info.get("duration", 0)),
                        "uploader": info.get("uploader", "未知作者"),
                        "upload_date": "",
                        "view_count": info.get("view_count", 0),
                        "like_count": info.get("like_count", 0),
                        "thumbnail": info.get("thumbnail_url", ""),
                    },
                }
            except Exception as pw_err:
                logger.warning(f"✗ Playwright 解析失败: {str(pw_err)[:200]}")
                
                # 方案 3：所有方案都失败，返回友好错误
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "快手视频解析失败（已尝试多种方案）\n\n"
                        "建议使用以下替代方案：\n"
                        "1. 使用 B站/YouTube 下载（更稳定）✅\n"
                        "2. 手动下载后通过'文件导入'上传 ✅\n\n"
                        f"技术详情:\n"
                        f"- videodl: {str(vdl_err)[:80]}\n"
                        f"- Playwright: {str(pw_err)[:80]}"
                    )
                )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解析快手视频失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=(
                f"解析失败: {str(e)[:100]}\n\n"
                "建议：\n"
                "1. 使用 B站/YouTube 下载\n"
                "2. 手动下载后通过'文件导入'上传"
            )
        )


@router.post("/download")
async def create_kuaishou_download_task(request: KuaishouDownloadRequest):
    """创建快手视频下载任务（使用混合方案）"""
    try:
        url = _parse_url_from_text(request.share_text)
        logger.info(f"创建快手下载任务: {url}")

        # 获取视频信息（优先 videodl）
        video_info = None
        
        # 方案 1：videodl
        try:
            from ...utils.kuaishou_videodl import get_kuaishou_video_info_videodl
            vdl_info = await get_kuaishou_video_info_videodl(url)
            # 包装为兼容对象
            class _VdlInfo:
                title = vdl_info.get("title", "快手视频")
                uploader = vdl_info.get("uploader", "快手用户")
                duration = int(vdl_info.get("duration", 0))
                view_count = vdl_info.get("view_count", 0)
                thumbnail_url = vdl_info.get("thumbnail_url", "")
            video_info = _VdlInfo()
            logger.info("✓ 使用 videodl 获取视频信息")
        except Exception as vdl_err:
            logger.warning(f"✗ videodl 获取信息失败: {str(vdl_err)[:100]}")
            
            # 方案 2：Playwright
            try:
                from ...utils.kuaishou_playwright import get_kuaishou_video_info_playwright
                pw_info = await get_kuaishou_video_info_playwright(url)
                class _PwInfo:
                    title = pw_info.get("title", "快手视频")
                    uploader = pw_info.get("uploader", "未知作者")
                    duration = int(pw_info.get("duration", 0))
                    view_count = pw_info.get("view_count", 0)
                    thumbnail_url = pw_info.get("thumbnail_url", "")
                video_info = _PwInfo()
                logger.info("✓ 使用 Playwright 获取视频信息")
            except Exception as pw_err:
                logger.warning(f"✗ Playwright 获取信息失败: {str(pw_err)[:100]}")
                # 使用默认信息
                class _DefaultInfo:
                    title = "快手视频"
                    uploader = "快手用户"
                    duration = 0
                    view_count = 0
                    thumbnail_url = ""
                video_info = _DefaultInfo()
                logger.info("使用默认视频信息")

        # 创建项目记录
        from ...core.database import SessionLocal
        from ...services.project_service import ProjectService
        from ...schemas.project import ProjectCreate, ProjectType, ProjectStatus

        db = SessionLocal()
        try:
            project_service = ProjectService(db)

            # 下载缩略图
            thumbnail_data = None
            if video_info.thumbnail_url:
                try:
                    import requests, base64
                    resp = requests.get(video_info.thumbnail_url, timeout=10)
                    if resp.status_code == 200:
                        thumbnail_data = "data:image/jpeg;base64," + base64.b64encode(resp.content).decode()
                except Exception as te:
                    logger.warning(f"下载快手缩略图失败: {te}")

            project_data = ProjectCreate(
                name=request.project_name,
                description=f"来自快手: {video_info.title}",
                project_type=ProjectType(request.video_category),
                status=ProjectStatus.PENDING,
                source_url=url,
                source_file=None,
                settings={
                    "download_status": "downloading",
                    "download_progress": 0.0,
                    "kuaishou_info": {
                        "url": url,
                        "title": video_info.title,
                        "uploader": video_info.uploader,
                        "duration": video_info.duration,
                        "view_count": video_info.view_count,
                        "thumbnail_url": video_info.thumbnail_url,
                    },
                    "video_category": request.video_category,
                },
            )

            project = project_service.create_project(project_data)
            project_id = str(project.id)

            if thumbnail_data:
                project.thumbnail = thumbnail_data
                db.commit()

            # 确保项目目录存在
            from ...core.path_utils import get_project_directory
            project_dir = get_project_directory(project_id)
            (project_dir / "raw").mkdir(parents=True, exist_ok=True)

            logger.info(f"快手项目已创建: {project_id}")

        finally:
            db.close()

        # 创建任务记录
        task_id = str(uuid.uuid4())
        task = KuaishouDownloadTask(
            id=task_id,
            url=url,
            project_name=request.project_name,
            video_category=request.video_category,
            status="pending",
            progress=0.0,
            project_id=project_id,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        download_tasks[task_id] = task

        # 异步执行下载
        from .async_task_manager import task_manager
        await task_manager.create_safe_task(
            f"kuaishou_download_{task_id}",
            _process_download,
            task_id,
            url,
            request,
            project_id,
        )

        return {
            "project_id": project_id,
            "task_id": task_id,
            "status": "created",
            "message": "项目已创建，正在下载中...",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建快手下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {e}")


@router.get("/tasks/{task_id}")
async def get_kuaishou_task_status(task_id: str):
    """获取下载任务状态"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return download_tasks[task_id]


@router.get("/tasks")
async def get_all_kuaishou_tasks():
    """获取所有快手下载任务"""
    return list(download_tasks.values())
