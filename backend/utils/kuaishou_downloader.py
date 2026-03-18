#!/usr/bin/env python3
"""
快手视频下载器 - 基于yt-dlp实现快手视频下载
支持从分享链接中下载视频，支持无水印下载
"""

import re
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable

import yt_dlp

logger = logging.getLogger(__name__)

# 快手链接正则模式
KUAISHOU_URL_PATTERNS = [
    r'https?://www\.kuaishou\.com/f/[A-Za-z0-9_\-]+',
    r'https?://www\.kuaishou\.com/short-video/[A-Za-z0-9_\-]+',
    r'https?://v\.kuaishou\.com/[A-Za-z0-9_\-]+',
]

# User-Agent
DESKTOP_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)


def extract_kuaishou_url(text: str) -> Optional[str]:
    """从快手分享文本中提取视频链接"""
    for pattern in KUAISHOU_URL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            url = match.group(0)
            # 移除查询参数，只保留基础 URL
            if '?' in url:
                url = url.split('?')[0]
            return url.rstrip('/')
    return None


def is_kuaishou_url(url: str) -> bool:
    """判断是否为快手链接"""
    return any(re.search(p, url) for p in KUAISHOU_URL_PATTERNS)


class KuaishouVideoInfo:
    """快手视频信息"""
    def __init__(self, info_dict: Dict[str, Any]):
        self.vid = info_dict.get('id', '')
        self.title = info_dict.get('title') or info_dict.get('description') or '快手视频'
        self.duration = info_dict.get('duration', 0)
        self.uploader = info_dict.get('uploader') or info_dict.get('creator') or '未知作者'
        self.description = info_dict.get('description', '')
        self.thumbnail_url = info_dict.get('thumbnail', '')
        self.view_count = info_dict.get('view_count', 0)
        self.like_count = info_dict.get('like_count', 0)
        self.upload_date = info_dict.get('upload_date', '')
        self.webpage_url = info_dict.get('webpage_url', '')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'vid': self.vid,
            'title': self.title,
            'duration': self.duration,
            'uploader': self.uploader,
            'description': self.description,
            'thumbnail_url': self.thumbnail_url,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'upload_date': self.upload_date,
            'webpage_url': self.webpage_url,
        }


class KuaishouDownloader:
    """快手视频下载器"""

    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = download_dir or Path.cwd()
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _base_ydl_opts(self) -> Dict[str, Any]:
        """通用 yt-dlp 基础选项"""
        return {
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': DESKTOP_UA,
                'Referer': 'https://www.kuaishou.com/',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            },
        }

    def _extract_info_sync(self, url: str, ydl_opts: Dict[str, Any]) -> Dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def _download_sync(self, url: str, ydl_opts: Dict[str, Any]) -> None:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """清理文件名，移除不合法字符"""
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
        sanitized = sanitized.strip(' .')
        if len(sanitized) > 80:
            sanitized = sanitized[:80]
        return sanitized or 'kuaishou_video'

    async def get_video_info(self, url: str) -> KuaishouVideoInfo:
        """获取视频信息（不下载），优先使用 Playwright"""
        loop = asyncio.get_event_loop()
        logger.info(f'解析快手视频信息 URL: {url}')

        # 方案 1：Playwright（推荐）
        try:
            from .kuaishou_playwright import get_kuaishou_video_info_playwright
            info = await get_kuaishou_video_info_playwright(url)
            logger.info(f'Playwright 解析成功: {info.get("title")}')
            
            # 转换为 KuaishouVideoInfo 格式
            class _PwInfo:
                vid = ''
                title = info.get('title', '快手视频')
                duration = int(info.get('duration', 0))
                uploader = info.get('uploader', '未知作者')
                description = info.get('title', '')
                thumbnail_url = info.get('thumbnail_url', '')
                view_count = info.get('view_count', 0)
                like_count = info.get('like_count', 0)
                upload_date = ''
                webpage_url = url
            
            return _PwInfo()
        except Exception as pw_err:
            logger.warning(f'Playwright 解析失败，尝试 yt-dlp 回退: {str(pw_err)[:100]}')

        # 方案 2：yt-dlp 回退
        base_opts = self._base_ydl_opts()
        try:
            info_dict = await loop.run_in_executor(None, self._extract_info_sync, url, base_opts)
            return KuaishouVideoInfo(info_dict)
        except Exception as e:
            raise RuntimeError(f"获取快手视频信息失败: {e}")

    @staticmethod
    def _create_progress_hook(callback: Callable[[str, float], None]):
        def hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    pct = downloaded / total * 80
                    speed = d.get('_speed_str', '')
                    callback(f"下载中 {speed}", pct)
            elif d['status'] == 'finished':
                callback("下载完成，处理中...", 85)
        return hook

    async def download_video(
        self,
        url: str,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> Dict[str, str]:
        """下载快手视频，优先使用 Playwright"""
        if progress_callback:
            progress_callback("正在解析视频信息...", 5)

        loop = asyncio.get_event_loop()
        logger.info(f'下载快手视频 URL: {url}')

        video_path = ""

        # 方案 1：Playwright 下载（推荐）
        try:
            from .kuaishou_playwright import KuaishouPlaywrightExtractor
            
            def progress_cb_sync(msg: str, pct: float):
                if progress_callback:
                    progress_callback(msg, pct)
            
            extractor = KuaishouPlaywrightExtractor(headless=True)
            video_path = await loop.run_in_executor(
                None,
                extractor.download_video_sync,
                url,
                self.download_dir,
                progress_cb_sync,
            )
            logger.info(f'Playwright 下载成功: {video_path}')
            
            if progress_callback:
                progress_callback("视频下载完成", 90)
            
            return {'video_path': video_path, 'subtitle_path': None}
            
        except Exception as pw_err:
            logger.warning(f'Playwright 下载失败，尝试 yt-dlp 回退: {str(pw_err)[:100]}')

        # 方案 2：yt-dlp 回退
        video_info = await self.get_video_info(url)
        safe_title = self._sanitize_filename(video_info.title)

        base_opts = self._base_ydl_opts()
        base_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': str(self.download_dir / f'{safe_title}.%(ext)s'),
            'noplaylist': True,
            'quiet': False,
        })
        if progress_callback:
            base_opts['progress_hooks'] = [self._create_progress_hook(progress_callback)]

        if progress_callback:
            progress_callback("开始下载视频...", 10)

        await loop.run_in_executor(None, self._download_sync, url, base_opts)

        video_path = self._find_video(safe_title)
        if not video_path:
            raise RuntimeError(f"下载完成但找不到视频文件，标题: {safe_title}")

        if progress_callback:
            progress_callback("视频下载完成", 90)

        return {'video_path': str(video_path), 'subtitle_path': None}

    def _find_video(self, safe_title: str) -> Optional[Path]:
        """在下载目录中查找视频文件"""
        for ext in ('mp4', 'mkv', 'webm', 'mov'):
            candidates = list(self.download_dir.glob(f'{safe_title}*.{ext}'))
            if candidates:
                return candidates[0]
        for ext in ('mp4', 'mkv', 'webm'):
            candidates = sorted(self.download_dir.glob(f'*.{ext}'), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                return candidates[0]
        return None


async def get_kuaishou_video_info(url: str) -> KuaishouVideoInfo:
    """便捷函数：获取快手视频信息"""
    downloader = KuaishouDownloader()
    return await downloader.get_video_info(url)
