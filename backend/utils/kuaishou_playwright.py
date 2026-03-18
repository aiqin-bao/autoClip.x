#!/usr/bin/env python3
"""
快手视频下载器 - 基于 Playwright 实现
通过浏览器自动化获取真实视频地址并下载
"""

import asyncio
import logging
import time
import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# 浏览器用户数据目录（持久化登录状态）
BROWSER_USER_DATA_DIR = Path.home() / '.autoclip' / 'kuaishou_browser_profile'


def _get_playwright_browsers_path() -> Optional[str]:
    """获取 Playwright 浏览器实际安装路径"""
    import os
    candidates = [
        os.path.expanduser('~/Library/Caches/ms-playwright'),   # macOS
        os.path.expanduser('~/.cache/ms-playwright'),           # Linux
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ms-playwright'),  # Windows
    ]
    for p in candidates:
        if p and Path(p).exists():
            return p
    return None


class KuaishouPlaywrightExtractor:
    """快手视频提取器 - 使用 Playwright"""

    def __init__(self, headless: bool = True):
        self.headless = headless

    def _setup_playwright_env(self):
        """设置 Playwright 环境变量"""
        import os
        browsers_path = _get_playwright_browsers_path()
        if browsers_path:
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', browsers_path)

    async def get_video_info(self, url: str) -> Dict[str, Any]:
        """获取视频信息"""
        self._setup_playwright_env()

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError('playwright 未安装，请运行: pip install playwright && playwright install chromium')

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
            )

            # 注入反检测脚本
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """)

            page = await context.new_page()
            
            # 用于捕获视频请求
            video_urls = []
            
            async def handle_response(response):
                """捕获视频资源请求"""
                url = response.url
                # 快手视频通常是 .mp4 或包含 video 关键词
                if ('.mp4' in url or 'video' in url.lower()) and response.status == 200:
                    content_type = response.headers.get('content-type', '')
                    if 'video' in content_type or url.endswith('.mp4'):
                        video_urls.append(url)
                        logger.info(f"捕获到视频 URL: {url[:100]}...")
            
            page.on('response', handle_response)

            try:
                # 访问视频页面
                logger.info(f"正在访问快手页面: {url}")
                await page.goto(url, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(5000)  # 等待视频加载

                # 提取页面信息
                info = await page.evaluate("""
                    () => {
                        // 提取标题
                        const title = document.querySelector('span[class*="title"]')?.textContent ||
                                    document.querySelector('h1')?.textContent ||
                                    document.querySelector('meta[property="og:title"]')?.content ||
                                    document.title || '快手视频';
                        
                        // 提取作者
                        const author = document.querySelector('a[class*="user"]')?.textContent ||
                                     document.querySelector('span[class*="author"]')?.textContent ||
                                     document.querySelector('meta[property="og:author"]')?.content ||
                                     '未知作者';
                        
                        // 提取统计信息
                        const stats = document.querySelectorAll('span[class*="count"]');
                        let viewCount = 0;
                        let likeCount = 0;
                        
                        stats.forEach(stat => {
                            const text = stat.textContent || '';
                            const num = parseInt(text.replace(/[^0-9]/g, '')) || 0;
                            if (text.includes('播放') || text.includes('观看')) {
                                viewCount = num;
                            } else if (text.includes('赞') || text.includes('点赞')) {
                                likeCount = num;
                            }
                        });
                        
                        // 提取视频元素
                        const video = document.querySelector('video');
                        const videoUrl = video?.src || video?.currentSrc || '';
                        
                        // 提取封面图
                        const poster = video?.poster || 
                                     document.querySelector('meta[property="og:image"]')?.content ||
                                     document.querySelector('img[class*="poster"]')?.src || '';
                        
                        return {
                            title: title.trim(),
                            uploader: author.trim(),
                            view_count: viewCount,
                            like_count: likeCount,
                            video_url: videoUrl,
                            thumbnail_url: poster,
                            duration: video?.duration || 0,
                        };
                    }
                """)

                await browser.close()

                # 优先使用捕获的视频 URL
                if video_urls:
                    info['video_url'] = video_urls[0]
                    logger.info(f"使用捕获的视频 URL: {video_urls[0][:100]}...")

                if not info.get('video_url'):
                    raise RuntimeError('无法提取视频地址，页面可能需要登录或视频已被删除')

                logger.info(f"成功提取快手视频信息: {info.get('title')}")
                return info

            except Exception as e:
                await browser.close()
                raise RuntimeError(f"提取视频信息失败: {e}")

    async def download_video(
        self,
        url: str,
        output_dir: Path,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> str:
        """下载视频"""
        if progress_callback:
            progress_callback("正在获取视频信息...", 10)

        # 获取视频信息
        info = await self.get_video_info(url)
        video_url = info.get('video_url')

        if not video_url:
            raise RuntimeError('无法获取视频下载地址')

        if progress_callback:
            progress_callback("开始下载视频...", 20)

        # 下载视频
        import aiohttp
        import aiofiles

        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理文件名
        title = info.get('title', 'kuaishou_video')
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:80]
        output_file = output_dir / f"{safe_title}.mp4"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        raise RuntimeError(f"下载失败: HTTP {response.status}")

                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0

                    async with aiofiles.open(output_file, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                            downloaded += len(chunk)

                            if progress_callback and total_size > 0:
                                progress = 20 + (downloaded / total_size) * 60
                                progress_callback(f"下载中 {downloaded}/{total_size}", progress)
        except Exception as e:
            # 删除不完整的文件
            if output_file.exists():
                output_file.unlink()
            raise RuntimeError(f"视频下载失败: {e}")

        # 验证文件完整性
        if not output_file.exists() or output_file.stat().st_size == 0:
            raise RuntimeError("下载的视频文件为空或不存在")

        if progress_callback:
            progress_callback("下载完成", 85)

        logger.info(f"视频下载完成: {output_file}")
        return str(output_file)

    def download_video_sync(
        self,
        url: str,
        output_dir: Path,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> str:
        """同步下载视频（用于线程池）"""
        return asyncio.run(self.download_video(url, output_dir, progress_callback))


async def get_kuaishou_video_info_playwright(url: str) -> Dict[str, Any]:
    """便捷函数：使用 Playwright 获取快手视频信息"""
    extractor = KuaishouPlaywrightExtractor(headless=True)
    return await extractor.get_video_info(url)


async def download_kuaishou_video_playwright(
    url: str,
    output_dir: Path,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> str:
    """便捷函数：使用 Playwright 下载快手视频"""
    extractor = KuaishouPlaywrightExtractor(headless=True)
    return await extractor.download_video(url, output_dir, progress_callback)
