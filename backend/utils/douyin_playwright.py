#!/usr/bin/env python3
"""
抖音 Playwright 提取器
用真实 Chromium 浏览器访问抖音页面，拦截 API 响应提取视频信息和下载链接。
完全绕过 yt-dlp + X-Bogus 签名问题。

持久化浏览器上下文：~/.autoclip/douyin_browser/
  - 首次登录后，浏览器 Profile（Cookie / localStorage / IndexedDB）持久保存
  - 后续操作可以无头模式直接使用，无需重复登录
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# 持久化浏览器数据目录
BROWSER_USER_DATA_DIR = Path.home() / '.autoclip' / 'douyin_browser'

# 登录状态文件（记录最后一次登录时间）
LOGIN_STATE_FILE = BROWSER_USER_DATA_DIR / 'login_state.json'


def _get_playwright_browsers_path() -> Optional[str]:
    candidates = [
        os.path.expanduser('~/Library/Caches/ms-playwright'),
        os.path.expanduser('~/.cache/ms-playwright'),
    ]
    for p in candidates:
        if p and Path(p).exists():
            return p
    return None


def _setup_playwright_env():
    path = _get_playwright_browsers_path()
    if path:
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', path)


def _save_login_state(logged_in: bool, cookies: List[dict]):
    BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        'logged_in': logged_in,
        'saved_at': time.time(),
        'cookie_count': len(cookies),
    }
    LOGIN_STATE_FILE.write_text(json.dumps(data), encoding='utf-8')


def get_browser_login_state() -> Dict[str, Any]:
    """读取持久化浏览器的登录状态"""
    if not LOGIN_STATE_FILE.exists():
        return {'logged_in': False, 'age_hours': None, 'cookie_count': 0}
    try:
        data = json.loads(LOGIN_STATE_FILE.read_text())
        age = (time.time() - data.get('saved_at', 0)) / 3600
        return {
            'logged_in': data.get('logged_in', False),
            'age_hours': round(age, 1),
            'cookie_count': data.get('cookie_count', 0),
            'valid': age < 7 * 24,  # 7 天内有效
        }
    except Exception:
        return {'logged_in': False, 'age_hours': None, 'cookie_count': 0}


def open_login_window_persistent(timeout_sec: int = 300) -> bool:
    """
    打开可见 Chromium 窗口（持久化 Profile），
    等待用户登录抖音后保存 Profile，后续可无头使用。
    """
    _setup_playwright_env()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error('playwright 未安装')
        return False

    BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f'启动持久化浏览器窗口，数据目录: {BROWSER_USER_DATA_DIR}')

    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_USER_DATA_DIR),
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--start-maximized',
                ],
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome={runtime:{}};"
            )
            page = ctx.new_page()
            page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=15000)

            deadline = time.time() + timeout_sec
            logged_in = False
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                cookie_names = {c['name'] for c in ctx.cookies()}
                # 检测登录标志
                if any(k in cookie_names for k in ('LOGIN_STATUS', 'sid_tt', 'sessionid', 'passport_csrf_token')):
                    logged_in = True
                    logger.info('检测到账号登录 Cookie')
                    break
                if '__ac_signature' in cookie_names:
                    logged_in = True
                    logger.info('检测到 __ac_signature，匿名 Cookie 可用')
                    break

            cookies = ctx.cookies()
            _save_login_state(logged_in, cookies)
            ctx.close()
            logger.info(f'持久化登录完成: logged_in={logged_in}, cookies={len(cookies)}')
            return logged_in

    except Exception as e:
        logger.error(f'持久化登录失败: {e}')
        return False


class DouyinPlaywrightExtractor:
    """
    用持久化 Chromium 浏览器提取抖音视频信息和下载链接。
    避免 yt-dlp + X-Bogus 签名验证问题。
    """

    API_DETAIL_PATH = '/aweme/v1/web/aweme/detail/'
    API_FEED_PATH = '/aweme/v1/web/tab/feed/'

    def __init__(self, headless: bool = True):
        self.headless = headless
        _setup_playwright_env()

    def _launch_context(self, pw):
        """启动持久化浏览器上下文"""
        BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_USER_DATA_DIR),
            headless=self.headless,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
            ],
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9'},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};"
        )
        return ctx

    def get_video_info_sync(self, url: str) -> Dict[str, Any]:
        """
        同步方式获取视频信息。
        策略：打开视频页面，拦截 /aweme/v1/web/aweme/detail/ 响应。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError('playwright 未安装，请运行: pip install playwright && playwright install chromium')

        captured: Dict[str, Any] = {}

        def on_response(resp):
            if self.API_DETAIL_PATH in resp.url and not captured:
                try:
                    body = resp.json()
                    aweme = (body.get('aweme_detail') or
                             (body.get('aweme_list') or [None])[0])
                    if aweme:
                        captured['aweme'] = aweme
                        logger.info(f'拦截到视频详情 API: {resp.url[:80]}')
                except Exception as e:
                    logger.debug(f'解析拦截响应失败: {e}')

        with sync_playwright() as pw:
            ctx = self._launch_context(pw)
            try:
                page = ctx.new_page()
                page.on('response', on_response)

                logger.info(f'Playwright 访问: {url}')
                page.goto(url, wait_until='domcontentloaded', timeout=20000)

                # 等待 API 响应（最多 15 秒）
                for _ in range(30):
                    if captured:
                        break
                    page.wait_for_timeout(500)

                # 如果 API 拦截失败，尝试从页面 JS 变量提取
                if not captured:
                    captured['aweme'] = self._extract_from_page(page)

            finally:
                ctx.close()

        if not captured.get('aweme'):
            state = get_browser_login_state()
            if not state.get('valid'):
                raise RuntimeError('NEED_LOGIN: 浏览器尚未登录抖音，请先点击【扫码登录】')
            raise RuntimeError('无法从抖音页面获取视频信息，请检查链接是否有效')

        return self._parse_aweme(captured['aweme'])

    def _extract_from_page(self, page) -> Optional[Dict]:
        """从页面 JS 变量提取视频数据（备用方案）"""
        scripts = [
            # RENDER_DATA 是抖音 SSR 注入的视频数据
            """
            (() => {
                try {
                    const rd = decodeURIComponent(window._ROUTER_DATA || '{}');
                    const obj = JSON.parse(rd);
                    const keys = Object.keys(obj);
                    for (const k of keys) {
                        const v = obj[k];
                        if (v && v.aweme_detail) return v.aweme_detail;
                        if (v && v.awemeDetail) return v.awemeDetail;
                    }
                } catch(e) {}
                return null;
            })()
            """,
            """
            (() => {
                try {
                    const els = document.querySelectorAll('script[id*="render"]');
                    for (const el of els) {
                        const t = el.textContent;
                        if (t && t.includes('aweme_detail')) {
                            const m = t.match(/\{.*"aweme_detail".*\}/s);
                            if (m) {
                                const obj = JSON.parse(m[0]);
                                if (obj.aweme_detail) return obj.aweme_detail;
                            }
                        }
                    }
                } catch(e) {}
                return null;
            })()
            """,
        ]
        for script in scripts:
            try:
                result = page.evaluate(script)
                if result:
                    logger.info('从页面 JS 变量提取到视频数据')
                    return result
            except Exception:
                pass
        return None

    def _parse_aweme(self, aweme: Dict) -> Dict[str, Any]:
        """将抖音 aweme_detail 解析为统一格式"""
        # 标题
        title = aweme.get('desc') or aweme.get('title') or '抖音视频'

        # 作者
        author = aweme.get('author') or {}
        uploader = author.get('nickname') or author.get('name') or '未知作者'

        # 时长（毫秒 → 秒）
        video = aweme.get('video') or {}
        duration_ms = video.get('duration') or aweme.get('duration') or 0
        duration = int(duration_ms / 1000) if duration_ms > 1000 else int(duration_ms)

        # 统计数据
        stats = aweme.get('statistics') or {}
        view_count = stats.get('play_count') or stats.get('comment_count') or 0
        like_count = stats.get('digg_count') or 0

        # 封面
        cover = video.get('cover') or video.get('origin_cover') or {}
        thumbnail = ''
        if isinstance(cover, dict):
            url_list = cover.get('url_list') or []
            thumbnail = url_list[0] if url_list else ''
        elif isinstance(cover, str):
            thumbnail = cover

        # 下载链接（取最高质量无水印）
        download_urls = self._extract_download_urls(video)

        # 视频 ID
        vid = aweme.get('aweme_id') or ''

        return {
            'vid': vid,
            'title': title,
            'uploader': uploader,
            'duration': duration,
            'view_count': view_count,
            'like_count': like_count,
            'thumbnail_url': thumbnail,
            'description': title,
            'download_urls': download_urls,
            'upload_date': aweme.get('create_time', ''),
            'webpage_url': f'https://www.douyin.com/video/{vid}' if vid else '',
        }

    def _extract_download_urls(self, video: Dict) -> List[str]:
        """从 video 对象提取所有可用下载链接（按质量排序）"""
        urls: List[str] = []

        # 尝试无水印下载链接（play_addr → download_addr → bit_rate）
        for key in ('play_addr', 'download_addr', 'play_addr_lowbr'):
            addr = video.get(key) or {}
            if isinstance(addr, dict):
                url_list = addr.get('url_list') or []
                urls.extend(url_list)

        # bit_rate 列表（包含不同质量）
        bit_rate = video.get('bit_rate') or []
        for br in bit_rate:
            play_addr = br.get('play_addr') or {}
            url_list = play_addr.get('url_list') or []
            urls.extend(url_list)

        # 去重、过滤空值
        seen = set()
        result = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                result.append(u)
        return result

    def download_video_sync(
        self,
        url: str,
        output_dir: Path,
        progress_callback=None,
    ) -> str:
        """
        下载抖音视频到 output_dir，返回本地文件路径。
        先获取视频信息拿到 download_urls，再用 requests 下载。
        """
        if progress_callback:
            progress_callback('正在解析视频页面...', 5)

        info = self.get_video_info_sync(url)
        download_urls = info.get('download_urls', [])
        if not download_urls:
            raise RuntimeError('无法获取视频下载链接')

        title = info.get('title', 'douyin_video')
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title)[:60] or 'douyin_video'
        output_path = output_dir / f'{safe_title}.mp4'
        output_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.douyin.com/',
            'Accept': '*/*',
        }

        last_err = None
        for dl_url in download_urls[:3]:
            try:
                if progress_callback:
                    progress_callback('开始下载视频...', 10)
                logger.info(f'尝试下载: {dl_url[:80]}')
                resp = requests.get(dl_url, headers=headers, stream=True, timeout=30)
                resp.raise_for_status()

                total = int(resp.headers.get('content-length', 0))
                downloaded = 0
                with open(output_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total > 0:
                                pct = 10 + (downloaded / total * 75)
                                progress_callback(f'下载中 {downloaded // 1024 // 1024}MB/{total // 1024 // 1024}MB', pct)

                if output_path.stat().st_size < 10000:
                    output_path.unlink(missing_ok=True)
                    raise RuntimeError('下载文件太小，可能不是有效视频')

                logger.info(f'视频下载成功: {output_path}')
                if progress_callback:
                    progress_callback('视频下载完成', 90)
                return str(output_path)

            except Exception as e:
                logger.warning(f'下载链接失败 ({dl_url[:60]}): {e}')
                last_err = e
                if output_path.exists():
                    output_path.unlink(missing_ok=True)
                continue

        raise RuntimeError(f'所有下载链接均失败: {last_err}')


# ── 异步包装器 ────────────────────────────────────────────────────────────────

async def get_douyin_video_info_playwright(url: str) -> Dict[str, Any]:
    """异步获取抖音视频信息（Playwright 方案）"""
    loop = asyncio.get_event_loop()
    extractor = DouyinPlaywrightExtractor(headless=True)
    return await loop.run_in_executor(None, extractor.get_video_info_sync, url)


async def download_douyin_video_playwright(
    url: str,
    output_dir: Path,
    progress_callback=None,
) -> str:
    """异步下载抖音视频（Playwright 方案）"""
    loop = asyncio.get_event_loop()
    extractor = DouyinPlaywrightExtractor(headless=True)
    return await loop.run_in_executor(
        None,
        extractor.download_video_sync,
        url,
        output_dir,
        progress_callback,
    )
