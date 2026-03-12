#!/usr/bin/env python3
"""
抖音视频下载器 - 基于yt-dlp实现抖音视频下载
支持从分享文本中自动提取链接，支持无水印下载

URL处理流程：
  v.douyin.com/xxx  →  展开短链  →  提取视频ID  →  www.douyin.com/video/{id}
"""

import re
import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable

import requests as _requests
import yt_dlp

# yt-dlp curl-cffi 指纹模拟（让请求看起来像真实 Chrome）
try:
    from yt_dlp.networking.impersonate import ImpersonateTarget as _ImpersonateTarget
    _IMPERSONATE_CHROME = _ImpersonateTarget('chrome')
    logger_init = logging.getLogger(__name__)
    logger_init.info('curl-cffi 可用，将使用 Chrome TLS 指纹')
except Exception:
    _IMPERSONATE_CHROME = None

# 持久化 Cookie 文件路径（登录后长期有效）
PERSISTENT_COOKIE_FILE = Path.home() / '.autoclip' / 'douyin_cookies.txt'
# Cookie 文件最长有效期（7 天）
COOKIE_MAX_AGE_SECS = 7 * 24 * 3600

# 全局登录状态（线程安全）
_login_status: Dict[str, Any] = {'status': 'idle', 'message': ''}
_login_lock = threading.Lock()

logger = logging.getLogger(__name__)

# 抖音链接正则模式（匹配各种输入格式）
DOUYIN_URL_PATTERNS = [
    r'https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?',
    r'https?://www\.douyin\.com/video/\d+',
    r'https?://www\.iesdouyin\.com/share/video/\d+',
    r'https?://vm\.tiktok\.com/[A-Za-z0-9_\-]+/?',
    r'https?://(www\.)?tiktok\.com/@[^/]+/video/\d+',
]

# yt-dlp 下载时使用的 User-Agent（模拟移动端）
MOBILE_UA = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
)


def extract_douyin_url(text: str) -> Optional[str]:
    """
    从抖音分享文本中提取视频链接。

    抖音分享文本示例：
    '5.30 复制打开抖音，看看【xx的作品】... https://v.douyin.com/zjv3JEE-J5M/ v@S.lP fbN:/ 11/11'
    """
    for pattern in DOUYIN_URL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(0).rstrip('/')
    return None


def is_douyin_url(url: str) -> bool:
    """判断是否为抖音/TikTok链接"""
    return any(re.search(p, url) for p in DOUYIN_URL_PATTERNS)


def _extract_video_id(url: str) -> Optional[str]:
    """从各种抖音URL格式中提取数字视频ID"""
    # douyin.com/video/ID 或 iesdouyin.com/share/video/ID
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    # tiktok.com/@user/video/ID
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    return None


def resolve_douyin_url(raw_url: str) -> str:
    """
    将任意抖音链接规范化为 yt-dlp 支持的格式：
      www.douyin.com/video/{id}

    处理流程：
    1. 如果已经是 douyin.com/video/{id} 直接返回
    2. 如果是短链 (v.douyin.com)，跟随 HTTP 重定向获取最终 URL
    3. 从最终 URL 中提取视频 ID，构造标准 URL
    """
    # 已经是标准格式
    if re.search(r'(?:www\.)?douyin\.com/video/\d+', raw_url):
        vid = _extract_video_id(raw_url)
        return f'https://www.douyin.com/video/{vid}'

    # 从 iesdouyin.com 直接提取 ID
    if 'iesdouyin.com' in raw_url:
        vid = _extract_video_id(raw_url)
        if vid:
            logger.info(f'从 iesdouyin URL 提取视频ID: {vid}')
            return f'https://www.douyin.com/video/{vid}'

    # 对短链或其他格式，跟随重定向解析真实 URL
    try:
        headers = {
            'User-Agent': MOBILE_UA,
            'Referer': 'https://www.douyin.com/',
        }
        resp = _requests.head(raw_url, headers=headers, allow_redirects=True, timeout=10)
        final_url = resp.url
        logger.info(f'短链展开: {raw_url} → {final_url}')

        # 尝试从最终 URL 提取视频 ID
        vid = _extract_video_id(final_url)
        if vid:
            return f'https://www.douyin.com/video/{vid}'

        # 如果 HEAD 不能拿到 Location，再用 GET
        resp2 = _requests.get(raw_url, headers=headers, allow_redirects=True, timeout=10)
        final_url2 = resp2.url
        vid = _extract_video_id(final_url2)
        if vid:
            logger.info(f'GET 展开后提取视频ID: {vid}')
            return f'https://www.douyin.com/video/{vid}'

        # 实在找不到 ID，回退到原始 URL 让 yt-dlp 自行处理
        logger.warning(f'无法从重定向 URL 提取视频ID，使用原始 URL: {raw_url}')
        return raw_url

    except Exception as e:
        logger.warning(f'短链解析失败 ({e})，使用原始 URL: {raw_url}')
        return raw_url


class DouyinVideoInfo:
    """抖音视频信息"""
    def __init__(self, info_dict: Dict[str, Any]):
        self.vid = info_dict.get('id', '')
        self.title = info_dict.get('title') or info_dict.get('description') or '抖音视频'
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


# 在 macOS 上按优先级尝试的浏览器列表
BROWSER_PRIORITY = ['chrome', 'safari', 'chromium', 'firefox', 'edge']

# 需要 Cookie 的错误关键词
_COOKIE_ERROR_KEYWORDS = (
    'fresh cookies', 'cookies', 'login', 'sign in',
    'permission denied', 'operation not permitted',
    'not found', 'no module',
)


def _needs_cookie(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(kw in msg for kw in _COOKIE_ERROR_KEYWORDS)


def _get_playwright_browsers_path() -> Optional[str]:
    """获取 Playwright 浏览器实际安装路径。"""
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


def _cookies_list_to_netscape(cookies: list) -> str:
    """
    将 Playwright cookie 列表转为 Netscape 文本格式。
    Session Cookie（expires=-1 或 None）使用默认 7 天过期时间。
    """
    lines = ['# Netscape HTTP Cookie File\n']
    for c in cookies:
        domain = c.get('domain', '.douyin.com')
        if not domain.startswith('.'):
            domain = '.' + domain
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        # Playwright 的 session cookie 返回 expires=-1；必须用 > 0 判断
        expires_raw = c.get('expires')
        if expires_raw is None or expires_raw <= 0:
            expires = int(time.time() + COOKIE_MAX_AGE_SECS)
        else:
            expires = int(expires_raw)
        path = c.get('path', '/')
        name = c.get('name', '')
        value = c.get('value', '')
        if not name:   # 跳过空名称的 Cookie（Playwright 偶尔产生）
            continue
        lines.append(f'{domain}\tTRUE\t{path}\t{secure}\t{expires}\t{name}\t{value}\n')
    return ''.join(lines)


def save_persistent_cookies(cookies: list) -> None:
    """将 Cookie 列表持久化保存到文件"""
    PERSISTENT_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERSISTENT_COOKIE_FILE.write_text(_cookies_list_to_netscape(cookies), encoding='utf-8')
    names = [c.get('name') for c in cookies]
    logger.info(f'持久化 Cookie 已保存: {PERSISTENT_COOKIE_FILE}，共 {len(cookies)} 个: {names}')


def load_persistent_cookie_file() -> Optional[str]:
    """
    返回持久化 Cookie 文件路径（如有效）。
    文件存在且未超过 COOKIE_MAX_AGE_SECS 则视为有效。
    """
    if not PERSISTENT_COOKIE_FILE.exists():
        return None
    age = time.time() - PERSISTENT_COOKIE_FILE.stat().st_mtime
    if age > COOKIE_MAX_AGE_SECS:
        logger.info(f'持久化 Cookie 文件已过期 ({age/3600:.1f}h)，需要重新登录')
        return None
    return str(PERSISTENT_COOKIE_FILE)


def get_login_status() -> Dict[str, Any]:
    """获取当前登录/Cookie 状态"""
    with _login_lock:
        status = dict(_login_status)

    # 补充持久化 Cookie 文件状态
    cookie_file = PERSISTENT_COOKIE_FILE
    if cookie_file.exists():
        age_h = (time.time() - cookie_file.stat().st_mtime) / 3600
        status['has_cookies'] = True
        status['cookie_age_hours'] = round(age_h, 1)
        status['cookie_valid'] = age_h < COOKIE_MAX_AGE_SECS / 3600
    else:
        status['has_cookies'] = False
        status['cookie_valid'] = False
    return status


def clear_persistent_cookies() -> None:
    """清除持久化 Cookie（强制重新登录）"""
    if PERSISTENT_COOKIE_FILE.exists():
        PERSISTENT_COOKIE_FILE.unlink()
        logger.info('持久化 Cookie 已清除')


def _pw_context_opts() -> Dict[str, Any]:
    """Playwright BrowserContext 通用参数"""
    return dict(
        user_agent=(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        ),
        locale='zh-CN',
        timezone_id='Asia/Shanghai',
        extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9'},
    )


def _antidetect_script() -> str:
    """注入 JS，隐藏 Playwright 自动化特征"""
    return """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}};
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
"""


def _run_login_flow_sync(timeout_sec: int = 300) -> None:
    """
    后台线程：打开真实 Chromium 窗口，用户扫码/登录抖音。
    成功后持久化保存 Cookie。
    """
    global _login_status
    import os

    browsers_path = _get_playwright_browsers_path()
    if browsers_path:
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', browsers_path)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        with _login_lock:
            _login_status = {'status': 'failed', 'message': 'playwright 未安装，请运行: pip install playwright && playwright install chromium'}
        return

    with _login_lock:
        _login_status = {'status': 'waiting', 'message': '浏览器窗口已打开，请在浏览器中扫码或登录抖音'}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--start-maximized',
                ],
            )
            ctx = browser.new_context(**_pw_context_opts())
            ctx.add_init_script(_antidetect_script())
            page = ctx.new_page()

            page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=20000)
            logger.info('抖音登录窗口已打开，等待用户操作...')

            deadline = time.time() + timeout_sec
            logged_in = False

            while time.time() < deadline:
                page.wait_for_timeout(2000)
                cookie_names = {c['name'] for c in ctx.cookies()}

                # 已登录标志
                if any(k in cookie_names for k in ('LOGIN_STATUS', 'passport_csrf_token', 'sessionid', 'sid_guard', 'sid_tt')):
                    logged_in = True
                    logger.info('检测到登录成功 Cookie')
                    break

                # 至少拿到 __ac_signature 也算可用
                if '__ac_signature' in cookie_names:
                    logged_in = True
                    logger.info('检测到 __ac_signature，Cookie 可用')
                    break

            all_cookies = ctx.cookies()
            browser.close()

        if all_cookies:
            save_persistent_cookies(all_cookies)
            cookie_names = [c.get('name') for c in all_cookies]
            is_auth = any(k in cookie_names for k in ('LOGIN_STATUS', 'sid_tt', 'sessionid'))
            with _login_lock:
                _login_status = {
                    'status': 'success',
                    'message': f'{"已登录账号" if is_auth else "匿名 Cookie"} 获取成功（{len(all_cookies)} 个）',
                    'authenticated': is_auth,
                }
        else:
            with _login_lock:
                _login_status = {'status': 'failed', 'message': '未能获取到 Cookie，请重试'}

    except Exception as e:
        logger.error(f'登录流程异常: {e}')
        with _login_lock:
            _login_status = {'status': 'failed', 'message': str(e)}


def start_login_flow(timeout_sec: int = 300) -> None:
    """非阻塞启动登录流程（后台线程）"""
    with _login_lock:
        if _login_status.get('status') == 'waiting':
            logger.info('登录流程已在进行中，跳过重复启动')
            return
    thread = threading.Thread(
        target=_run_login_flow_sync,
        args=(timeout_sec,),
        daemon=True,
        name='DouYinLogin',
    )
    thread.start()
    logger.info('已启动抖音登录后台线程')


def _generate_cookies_via_playwright() -> Optional[str]:
    """
    使用 Playwright 无头浏览器访问 douyin.com，获取包含
    __ac_signature / __ac_nonce / ttwid 等 JS 动态生成 Cookie，
    写入 Netscape 格式临时文件供 yt-dlp 使用。
    """
    import tempfile, os, time

    browsers_path = _get_playwright_browsers_path()
    if browsers_path:
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', browsers_path)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning('playwright 未安装，跳过自动 Cookie 获取')
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                ],
            )
            ctx = browser.new_context(**_pw_context_opts())
            ctx.add_init_script(_antidetect_script())
            page = ctx.new_page()

            # 访问抖音主页触发 JS Cookie 生成（__ac_signature 等）
            page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(4000)   # 等待 JS 执行完成

            cookies = ctx.cookies()
            browser.close()

        if not cookies:
            logger.warning('Playwright 未获取到 Cookie')
            return None

        cookie_file = Path(tempfile.mktemp(suffix='-douyin-pw.txt'))
        cookie_file.write_text(_cookies_list_to_netscape(cookies), encoding='utf-8')

        cookie_names = [c.get('name') for c in cookies]
        logger.info(f'Playwright Cookie 文件: {cookie_file}，共 {len(cookies)} 个: {cookie_names}')
        return str(cookie_file)

    except Exception as e:
        logger.warning(f'Playwright 获取 Cookie 失败: {e}')
        return None


def _generate_fresh_cookies_file() -> Optional[str]:
    """
    通过 HTTP 请求访问 douyin.com，获取服务端下发的 ttwid 等 Cookie，
    写入 Netscape 格式临时文件，供 yt-dlp 使用。
    """
    import tempfile, time
    try:
        desktop_ua = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        )
        session = _requests.Session()
        session.headers.update({
            'User-Agent': desktop_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.douyin.com/',
        })

        # 先访问主页获取 __ac_nonce 等初始 Cookie
        session.get('https://www.douyin.com/', timeout=15, allow_redirects=True)

        # 注册 ttwid（ByteDance 统一会话 Token，yt-dlp DouyinIE 会校验它）
        try:
            ttwid_resp = session.post(
                'https://ttwid.bytedance.com/ttwid/union/register/',
                json={
                    'region': 'cn',
                    'aid': 6383,
                    'needFid': False,
                    'service': 'www.douyin.com',
                    'migrate_info': {'ticket': '', 'source': 'node'},
                    'cbUrlProtocol': 'https',
                    'union': True,
                },
                headers={'Content-Type': 'application/json'},
                timeout=10,
            )
            data = ttwid_resp.json()
            ttwid_value = (data.get('data') or {}).get('ttwid') or ''
            if ttwid_value:
                session.cookies.set(
                    'ttwid', ttwid_value,
                    domain='.douyin.com', path='/',
                )
                logger.info(f'成功获取 ttwid: {ttwid_value[:30]}...')
        except Exception as te:
            logger.warning(f'获取 ttwid 失败（将继续）: {te}')

        if not session.cookies:
            logger.warning('自动获取 Cookie 失败：响应未包含 Cookie')
            return None

        cookie_file = Path(tempfile.mktemp(suffix='-douyin.txt'))
        with open(cookie_file, 'w') as f:
            f.write('# Netscape HTTP Cookie File\n')
            for c in session.cookies:
                domain = c.domain or '.douyin.com'
                if not domain.startswith('.'):
                    domain = '.' + domain
                secure = 'TRUE' if c.secure else 'FALSE'
                expires = int(c.expires or (time.time() + 3600 * 24 * 7))
                f.write(f'{domain}\tTRUE\t{c.path or "/"}\t{secure}\t{expires}\t{c.name}\t{c.value}\n')

        cookie_names = [c.name for c in session.cookies]
        logger.info(f'自动 Cookie 文件: {cookie_file}，包含: {cookie_names}')
        return str(cookie_file)

    except Exception as e:
        logger.warning(f'自动获取 Cookie 失败: {e}')
        return None


class DouyinDownloader:
    """抖音视频下载器"""

    def __init__(
        self,
        download_dir: Optional[Path] = None,
        browser: Optional[str] = None,
        cookies_file: Optional[str] = None,
    ):
        self.download_dir = download_dir or Path.cwd()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        # 记录上次成功的浏览器，下次优先使用
        self._good_browser: Optional[str] = browser
        # 用户手动指定的 Cookie 文件（最高优先级）
        self.cookies_file: Optional[str] = cookies_file

    def _base_ydl_opts(self, browser: Optional[str] = None) -> Dict[str, Any]:
        """通用 yt-dlp 基础选项，可选注入浏览器 Cookie"""
        opts: Dict[str, Any] = {
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                'Referer': 'https://www.douyin.com/',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            },
        }
        # 使用 Chrome TLS 指纹（通过 curl-cffi），绕过 Douyin TLS 检测
        if _IMPERSONATE_CHROME is not None:
            opts['impersonate'] = _IMPERSONATE_CHROME
        if browser:
            opts['cookiesfrombrowser'] = (browser,)
        return opts

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
        return sanitized or 'douyin_video'

    def _browsers_to_try(self) -> list:
        """返回要尝试的浏览器列表（缓存成功的优先）"""
        if self._good_browser:
            rest = [b for b in BROWSER_PRIORITY if b != self._good_browser]
            return [self._good_browser] + rest
        return BROWSER_PRIORITY

    async def _run_with_cookie_fallback(self, fn_sync, url: str, base_opts: Dict[str, Any]):
        """
        按优先级尝试以下方式获取 Cookie：
          1. 自动 HTTP 请求生成 Cookie 文件（最稳定）
          2. 上次成功的浏览器 Cookie
          3. 其他浏览器 Cookie
        """
        loop = asyncio.get_event_loop()
        last_err: Exception = RuntimeError("未知错误")

        # ── 方案 0：用户手动指定 Cookie 文件（最高优先级） ──────────
        if self.cookies_file and Path(self.cookies_file).exists():
            opts = {**base_opts, 'cookiefile': self.cookies_file}
            try:
                result = await loop.run_in_executor(None, fn_sync, url, opts)
                logger.info(f'使用用户 Cookie 文件成功: {self.cookies_file}')
                return result
            except Exception as e:
                logger.warning(f'用户 Cookie 文件失败: {e}')
                last_err = e
                if not _needs_cookie(str(e)):
                    raise RuntimeError(f"下载失败: {e}")

        # ── 方案 0.5：持久化登录 Cookie（扫码登录后保存的）──────────
        persistent = load_persistent_cookie_file()
        if persistent:
            opts = {**base_opts, 'cookiefile': persistent}
            try:
                result = await loop.run_in_executor(None, fn_sync, url, opts)
                logger.info(f'使用持久化 Cookie 成功: {persistent}')
                return result
            except Exception as e:
                err_str = str(e)
                logger.info(f'持久化 Cookie 失败 ({err_str[:80]})，尝试重新获取...')
                last_err = e
                if not _needs_cookie(err_str):
                    raise RuntimeError(f"下载失败: {e}")

        # ── 方案 1：Playwright 无头浏览器获取真实 JS Cookie ────────
        logger.info('尝试 Playwright 获取抖音 Cookie...')
        pw_cookie_file = await loop.run_in_executor(None, _generate_cookies_via_playwright)
        if pw_cookie_file:
            opts = {**base_opts, 'cookiefile': pw_cookie_file}
            try:
                result = await loop.run_in_executor(None, fn_sync, url, opts)
                logger.info('使用 Playwright Cookie 成功')
                return result
            except Exception as e:
                err_str = str(e)
                logger.info(f'Playwright Cookie 失败 ({err_str[:100]})，尝试 HTTP 生成...')
                last_err = e
                if not _needs_cookie(err_str):
                    raise RuntimeError(f"下载失败: {e}")
            finally:
                try:
                    Path(pw_cookie_file).unlink(missing_ok=True)
                except Exception:
                    pass

        # ── 方案 2：HTTP 请求生成 Cookie 文件 ────────────────────
        cookie_file = await loop.run_in_executor(None, _generate_fresh_cookies_file)
        if cookie_file:
            opts = {**base_opts, 'cookiefile': cookie_file}
            try:
                result = await loop.run_in_executor(None, fn_sync, url, opts)
                logger.info('使用 HTTP Cookie 成功')
                return result
            except Exception as e:
                err_str = str(e)
                logger.info(f'HTTP Cookie 失败 ({err_str[:100]})，尝试浏览器 Cookie...')
                last_err = e
                if not _needs_cookie(err_str):
                    raise RuntimeError(f"下载失败: {e}")
            finally:
                try:
                    Path(cookie_file).unlink(missing_ok=True)
                except Exception:
                    pass

        # ── 方案 2 & 3：浏览器 Cookie ──────────────────────────────
        for browser in self._browsers_to_try():
            opts = {**base_opts, 'cookiesfrombrowser': (browser,)}
            try:
                result = await loop.run_in_executor(None, fn_sync, url, opts)
                self._good_browser = browser
                logger.info(f'使用 {browser} cookies 成功')
                return result
            except Exception as e:
                err_str = str(e)
                logger.info(f'浏览器 {browser} cookies 失败: {err_str[:100]}')
                last_err = e
                if not _needs_cookie(err_str):
                    raise RuntimeError(f"下载失败: {e}")
                continue

        raise RuntimeError(
            "NEED_LOGIN: 无法获取有效的抖音 Cookie。\n\n"
            "请点击【扫码登录抖音】按钮，在弹出的浏览器窗口中完成登录后重试。\n\n"
            f"详细错误：{last_err}"
        )

    async def get_video_info(self, url: str) -> DouyinVideoInfo:
        """获取视频信息（不下载），自动尝试多个浏览器 Cookie"""
        loop = asyncio.get_event_loop()
        resolved_url = await loop.run_in_executor(None, resolve_douyin_url, url)
        logger.info(f'解析视频信息 URL: {resolved_url}')

        base_opts = self._base_ydl_opts()
        try:
            info_dict = await self._run_with_cookie_fallback(
                self._extract_info_sync, resolved_url, base_opts
            )
            return DouyinVideoInfo(info_dict)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"获取抖音视频信息失败: {e}")

    @staticmethod
    def _create_progress_hook(callback: Callable[[str, float], None]):
        def hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    pct = downloaded / total * 80  # 下载占 80%
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
        """
        下载抖音视频（无水印），返回本地文件路径。
        
        Returns:
            {'video_path': str, 'subtitle_path': None}
        """
        if progress_callback:
            progress_callback("正在解析视频信息...", 5)

        loop = asyncio.get_event_loop()

        # 规范化 URL
        resolved_url = await loop.run_in_executor(None, resolve_douyin_url, url)
        logger.info(f'下载 URL: {resolved_url}')

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

        # 下载时同样使用 Cookie 回退机制
        def _download_wrapper(u, opts):
            self._download_sync(u, opts)
            return None

        await self._run_with_cookie_fallback(_download_wrapper, resolved_url, base_opts)

        # 查找下载好的视频文件
        video_path = self._find_video(safe_title)
        if not video_path:
            raise RuntimeError(f"下载完成但找不到视频文件，标题: {safe_title}")

        if progress_callback:
            progress_callback("视频下载完成", 90)

        # 抖音视频通常没有外挂字幕，后续由 Whisper/ASR 处理
        return {'video_path': str(video_path), 'subtitle_path': None}

    def _find_video(self, safe_title: str) -> Optional[Path]:
        """在下载目录中查找视频文件"""
        for ext in ('mp4', 'mkv', 'webm', 'mov'):
            candidates = list(self.download_dir.glob(f'{safe_title}*.{ext}'))
            if candidates:
                return candidates[0]
        # 宽泛搜索（标题可能被截断）
        for ext in ('mp4', 'mkv', 'webm'):
            candidates = sorted(self.download_dir.glob(f'*.{ext}'), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                return candidates[0]
        return None


async def get_douyin_video_info(url: str) -> DouyinVideoInfo:
    """便捷函数：获取抖音视频信息"""
    downloader = DouyinDownloader()
    return await downloader.get_video_info(url)
