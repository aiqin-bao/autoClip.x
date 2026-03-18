"""
抖音视频导入 API
支持从抖音分享文本中自动提取链接，解析视频信息，下载并启动切片流水线
"""

import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Form
from pydantic import BaseModel

from ...utils.douyin_downloader import (
    DouyinDownloader,
    extract_douyin_url,
    is_douyin_url,
    get_douyin_video_info,
    start_login_flow,
    get_login_status,
    clear_persistent_cookies,
)
from ...utils.douyin_playwright import (
    DouyinPlaywrightExtractor,
    get_douyin_video_info_playwright,
    download_douyin_video_playwright,
    open_login_window_persistent,
    get_browser_login_state,
)
from ...core.config import get_data_directory

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存中的下载任务状态
download_tasks: dict = {}


# ---------- Pydantic 模型 ----------

class DouyinParseRequest(BaseModel):
    share_text: str  # 可以是完整分享文本或纯链接


class DouyinDownloadRequest(BaseModel):
    share_text: str          # 分享文本或纯链接
    project_name: str
    video_category: Optional[str] = "default"


class DouyinDownloadTask(BaseModel):
    id: str
    url: str
    project_name: str
    video_category: str
    status: str              # pending / processing / completed / failed
    progress: float
    error_message: Optional[str] = None
    project_id: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- 辅助函数 ----------

def _parse_url_from_text(share_text: str) -> str:
    """从分享文本中提取链接，失败时原样返回"""
    url = extract_douyin_url(share_text)
    if url:
        return url
    # 若已是纯链接直接返回
    stripped = share_text.strip()
    if is_douyin_url(stripped):
        return stripped
    raise ValueError(
        "无法从文本中识别抖音链接，请确保包含 v.douyin.com 或 www.douyin.com 的链接"
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

async def _process_download(task_id: str, url: str, request: DouyinDownloadRequest, project_id: str):
    """后台下载并处理抖音视频"""
    try:
        download_tasks[task_id].status = "processing"
        download_tasks[task_id].progress = 10.0
        await _update_project_progress(project_id, 10.0, "正在连接抖音服务器...")

        # 下载视频（优先 Playwright 方案，回退到 yt-dlp）
        data_dir = get_data_directory()
        download_dir = data_dir / "temp"
        download_dir.mkdir(exist_ok=True)

        def progress_cb_sync(msg: str, pct: float):
            download_tasks[task_id].progress = max(10.0, min(pct, 85.0))

        video_path = ""
        subtitle_path = None

        # ── Playwright 下载（主路径）─────────────────────────────
        try:
            loop = asyncio.get_running_loop()
            from pathlib import Path as _Path
            extractor = DouyinPlaywrightExtractor(headless=True)
            video_path = await loop.run_in_executor(
                None,
                extractor.download_video_sync,
                url,
                download_dir,
                progress_cb_sync,
            )
            logger.info(f"Playwright 下载成功: {video_path}")
        except Exception as pw_err:
            pw_err_str = str(pw_err)
            logger.warning(f"Playwright 下载失败，回退 yt-dlp: {pw_err_str[:120]}")
            if "NEED_LOGIN" in pw_err_str:
                raise RuntimeError(pw_err_str)

            # ── yt-dlp 回退 ─────────────────────────────────────
            downloader = DouyinDownloader(download_dir=download_dir)

            async def progress_cb(msg: str, pct: float):
                download_tasks[task_id].progress = max(10.0, min(pct, 85.0))
                await _update_project_progress(project_id, download_tasks[task_id].progress, msg)

            download_result = await downloader.download_video(url, progress_callback=progress_cb)
            video_path = download_result.get("video_path", "")
            subtitle_path = download_result.get("subtitle_path")

        await _update_project_progress(project_id, 60.0, "视频下载完成，正在生成字幕...")

        # 用 Whisper 生成字幕（抖音无外挂字幕）
        if video_path and not subtitle_path:
            logger.info("抖音视频无外挂字幕，启动 Whisper ASR...")
            await _update_project_progress(project_id, 70.0, "正在使用 Whisper 识别字幕...")
            try:
                from ...utils.speech_recognizer import generate_subtitle_for_video, SpeechRecognitionError
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
                logger.info(f"抖音项目 {project_id} 流水线已启动")
            except Exception as e:
                logger.error(f"启动流水线失败: {e}")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"抖音下载任务失败 [{task_id}]: {e}")
        if task_id in download_tasks:
            download_tasks[task_id].status = "failed"
            download_tasks[task_id].error_message = str(e)
            download_tasks[task_id].updated_at = datetime.now().isoformat()
        await _update_project_progress(project_id, 0.0, f"下载失败: {e}")


# ---------- API 路由 ----------

@router.post("/parse")
async def parse_douyin_video(share_text: str = Form(...)):
    """
    解析抖音视频信息。
    优先使用 Playwright 持久化浏览器（绕过 X-Bogus 限制），
    失败时回退到 yt-dlp。
    """
    try:
        url = _parse_url_from_text(share_text)
        logger.info(f"解析抖音视频: {url}")

        # ── 方案 1：Playwright 持久化浏览器（推荐） ──────────────
        try:
            info = await get_douyin_video_info_playwright(url)
            logger.info(f"Playwright 解析成功: {info.get('title')}")
            return {
                "success": True,
                "extracted_url": url,
                "video_info": {
                    "title": info.get("title"),
                    "description": info.get("description"),
                    "duration": info.get("duration"),
                    "uploader": info.get("uploader"),
                    "upload_date": str(info.get("upload_date", "")),
                    "view_count": info.get("view_count", 0),
                    "like_count": info.get("like_count", 0),
                    "thumbnail": info.get("thumbnail_url"),
                },
            }
        except RuntimeError as pw_err:
            err_msg = str(pw_err)
            if "NEED_LOGIN" in err_msg:
                raise  # 直接向上抛，让前端显示登录提示
            logger.warning(f"Playwright 解析失败，尝试 yt-dlp 回退: {err_msg[:100]}")

        # ── 方案 2：yt-dlp 回退 ──────────────────────────────
        video_info = await get_douyin_video_info(url)
        logger.info(f"yt-dlp 解析成功: {video_info.title}")
        return {
            "success": True,
            "extracted_url": url,
            "video_info": {
                "title": video_info.title,
                "description": video_info.description,
                "duration": video_info.duration,
                "uploader": video_info.uploader,
                "upload_date": video_info.upload_date,
                "view_count": video_info.view_count,
                "like_count": video_info.like_count,
                "thumbnail": video_info.thumbnail_url,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        err_str = str(e)
        logger.error(f"解析抖音视频失败: {err_str[:200]}")
        raise HTTPException(status_code=500, detail=err_str)
    except Exception as e:
        logger.error(f"解析抖音视频失败: {e}")
        raise HTTPException(status_code=500, detail=f"解析失败: {e}")


@router.post("/download")
async def create_douyin_download_task(request: DouyinDownloadRequest):
    """创建抖音视频下载任务，立即创建项目并异步下载"""
    try:
        url = _parse_url_from_text(request.share_text)
        logger.info(f"创建抖音下载任务: {url}")

        # 获取视频信息（优先 Playwright，回退 yt-dlp）
        try:
            pw_info = await get_douyin_video_info_playwright(url)
            # 包装为 DouyinVideoInfo 兼容对象
            class _PwInfo:
                title = pw_info.get("title", "抖音视频")
                uploader = pw_info.get("uploader", "未知作者")
                duration = pw_info.get("duration", 0)
                view_count = pw_info.get("view_count", 0)
                thumbnail_url = pw_info.get("thumbnail_url", "")
            video_info = _PwInfo()
        except Exception:
            video_info = await get_douyin_video_info(url)

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
                    logger.warning(f"下载抖音缩略图失败: {te}")

            project_data = ProjectCreate(
                name=request.project_name,
                description=f"来自抖音: {video_info.title}",
                project_type=ProjectType(request.video_category),
                status=ProjectStatus.PENDING,
                source_url=url,
                source_file=None,
                settings={
                    "download_status": "downloading",
                    "download_progress": 0.0,
                    "douyin_info": {
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

            logger.info(f"抖音项目已创建: {project_id}")

        finally:
            db.close()

        # 创建任务记录
        task_id = str(uuid.uuid4())
        task = DouyinDownloadTask(
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
            f"douyin_download_{task_id}",
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
        logger.error(f"创建抖音下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {e}")


@router.get("/tasks/{task_id}")
async def get_douyin_task_status(task_id: str):
    """获取下载任务状态"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return download_tasks[task_id]


@router.get("/tasks")
async def get_all_douyin_tasks():
    """获取所有抖音下载任务"""
    return list(download_tasks.values())


# ---------- 登录相关路由 ----------

@router.post("/login/start")
async def start_douyin_login(force: bool = False):
    """
    启动扫码登录流程：打开真实 Chromium 浏览器窗口（持久化 Profile），
    用户在窗口内扫码/登录抖音后，浏览器 Profile 自动保存供后续无头使用。
    force=true 时即使已登录也强制重新打开窗口。
    """
    # 已登录且不强制刷新时直接返回
    if not force:
        pw_state = get_browser_login_state()
        cookie_state = get_login_status()
        if pw_state.get("valid", False) or cookie_state.get("cookie_valid", False):
            return {
                "status": "already_logged_in",
                "message": "已处于登录状态，无需重新扫码。如需切换账号，请先清除 Cookie 后重试。",
            }

    import threading
    def _run():
        open_login_window_persistent(timeout_sec=300)
    t = threading.Thread(target=_run, daemon=True, name='DouyinPWLogin')
    t.start()
    return {
        "status": "started",
        "message": "浏览器窗口正在打开，请在弹出的 Chromium 窗口中登录抖音（支持扫码登录）",
    }


@router.get("/login/status")
async def douyin_login_status():
    """获取当前登录状态（持久化浏览器 + Cookie 双重检查）"""
    pw_state = get_browser_login_state()
    cookie_state = get_login_status()
    # 合并两种状态
    valid = pw_state.get('valid', False) or cookie_state.get('cookie_valid', False)
    return {
        "status": "success" if valid else cookie_state.get("status", "idle"),
        "message": cookie_state.get("message", ""),
        "has_cookies": cookie_state.get("has_cookies", False) or pw_state.get('cookie_count', 0) > 0,
        "cookie_valid": valid,
        "cookie_age_hours": pw_state.get("age_hours") or cookie_state.get("cookie_age_hours"),
        "authenticated": pw_state.get("logged_in", False),
        "browser_profile": pw_state.get("valid", False),
    }


@router.delete("/login/cookies")
async def clear_douyin_cookies():
    """清除已保存的 Cookie 和浏览器 Profile（下次操作需重新登录）"""
    import shutil
    from ...utils.douyin_playwright import BROWSER_USER_DATA_DIR, LOGIN_STATE_FILE
    from ...utils.douyin_downloader import clear_persistent_cookies
    clear_persistent_cookies()
    if LOGIN_STATE_FILE.exists():
        LOGIN_STATE_FILE.unlink()
    return {"success": True, "message": "Cookie 和浏览器 Profile 已清除"}
