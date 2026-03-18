#!/usr/bin/env python3
"""
快手视频下载器 - 基于 videodl 实现
使用多个通用解析器，提供高可靠性的下载方案
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


class KuaishouVideoDLDownloader:
    """基于 videodl 的快手下载器
    
    使用多个通用解析器按优先级尝试，提供高可靠性的下载方案
    """
    
    # 按优先级排序的解析器列表（基于测试和社区反馈）
    PARSERS = [
        'VideoFKVideoClient',      # 免费短视频下载器（推荐）
        'SnapAnyVideoClient',       # SnapAny万能解析
        'GVVideoClient',            # GreenVideo视频下载
        'KedouVideoClient',         # Kedou视频解析
        'AnyFetcherVideoClient',    # 万能视频下载器
        'IIILabVideoClient',        # 兽音译者
        'KuKuToolVideoClient',      # KuKuTool视频解析
        'KuaishouVideoClient',      # 原生快手客户端（备选）
    ]
    
    def __init__(self, download_dir: Path):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._last_successful_parser: Optional[str] = None
    
    def _get_parser_order(self) -> list:
        """获取解析器尝试顺序（优先使用上次成功的）"""
        if self._last_successful_parser and self._last_successful_parser in self.PARSERS:
            # 将上次成功的解析器放在第一位
            parsers = [self._last_successful_parser]
            parsers.extend([p for p in self.PARSERS if p != self._last_successful_parser])
            return parsers
        return self.PARSERS.copy()
    
    async def get_video_info(self, url: str) -> Dict[str, Any]:
        """获取视频信息
        
        Args:
            url: 快手视频链接
            
        Returns:
            视频信息字典
            
        Raises:
            RuntimeError: 所有解析器均失败
        """
        try:
            from videodl import videodl
        except ImportError:
            raise RuntimeError(
                'videofetch 未安装，请运行: pip install videofetch\n'
                '注意：还需要安装 FFmpeg 才能正常使用'
            )
        
        parsers = self._get_parser_order()
        last_error = None
        
        for parser in parsers:
            try:
                logger.info(f"尝试使用 {parser} 解析快手视频...")
                
                video_client = videodl.VideoClient(
                    allowed_video_sources=[parser],
                    apply_common_video_clients_only=True,
                    init_video_clients_cfg={
                        parser: {'work_dir': str(self.download_dir)}
                    }
                )
                
                # 解析视频信息
                video_infos = video_client.parsefromurl(url)
                
                if video_infos and len(video_infos) > 0:
                    info = video_infos[0]
                    
                    # 检查是否成功获取下载链接
                    if not info.get('download_url'):
                        logger.warning(f"{parser} 未能获取下载链接")
                        continue
                    
                    self._last_successful_parser = parser
                    logger.info(f"✓ {parser} 解析成功: {info.get('title', '未知标题')}")
                    
                    return {
                        'title': info.get('title', '快手视频'),
                        'video_url': info.get('download_url', ''),
                        'duration': 0,  # videodl 通常不提供时长
                        'uploader': '快手用户',
                        'thumbnail_url': '',
                        'view_count': 0,
                        'like_count': 0,
                        'parser_used': parser,
                        '_raw_info': info,  # 保存原始信息供下载使用
                    }
                else:
                    logger.warning(f"{parser} 返回空结果")
                    
            except Exception as e:
                last_error = e
                logger.warning(f"✗ {parser} 解析失败: {str(e)[:100]}")
                continue
        
        # 所有解析器都失败
        error_msg = (
            f"所有解析器均失败（尝试了 {len(parsers)} 个）\n"
            f"最后错误: {last_error}\n\n"
            "建议：\n"
            "1. 检查链接是否有效\n"
            "2. 确认已安装 FFmpeg\n"
            "3. 尝试使用 B站/YouTube（更稳定）\n"
            "4. 手动下载后通过'文件导入'上传"
        )
        raise RuntimeError(error_msg)
    
    async def download_video(
        self, 
        url: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> str:
        """下载视频
        
        Args:
            url: 快手视频链接
            progress_callback: 进度回调函数
            
        Returns:
            下载的视频文件路径
            
        Raises:
            RuntimeError: 所有下载方案均失败
        """
        try:
            from videodl import videodl
        except ImportError:
            raise RuntimeError(
                'videofetch 未安装，请运行: pip install videofetch\n'
                '注意：还需要安装 FFmpeg 才能正常使用'
            )
        
        if progress_callback:
            progress_callback("正在解析视频信息...", 10)
        
        parsers = self._get_parser_order()
        last_error = None
        
        for idx, parser in enumerate(parsers):
            try:
                if progress_callback:
                    progress = 10 + (idx / len(parsers)) * 10
                    progress_callback(f"尝试 {parser}...", progress)
                
                logger.info(f"尝试使用 {parser} 下载快手视频...")
                
                video_client = videodl.VideoClient(
                    allowed_video_sources=[parser],
                    apply_common_video_clients_only=True,
                    init_video_clients_cfg={
                        parser: {'work_dir': str(self.download_dir)}
                    }
                )
                
                # 解析视频信息
                video_infos = video_client.parsefromurl(url)
                
                if not video_infos or len(video_infos) == 0:
                    logger.warning(f"{parser} 返回空结果")
                    continue
                
                info = video_infos[0]
                
                if not info.get('download_url'):
                    logger.warning(f"{parser} 未能获取下载链接")
                    continue
                
                if progress_callback:
                    progress_callback(f"开始下载（使用 {parser}）...", 30)
                
                # 下载视频
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    video_client.download,
                    video_infos
                )
                
                # 查找下载的文件
                video_file = Path(info['file_path'])
                
                # 如果是 m3u/m3u8 文件，查找转换后的 mp4
                if video_file.suffix.lower() in ['.m3u', '.m3u8']:
                    # videodl 会将 m3u8 转换为 mp4
                    mp4_file = video_file.with_suffix('.mp4')
                    if mp4_file.exists():
                        video_file = mp4_file
                    else:
                        # 查找同名的其他视频文件
                        for ext in ['.mp4', '.mkv', '.webm']:
                            alt_file = video_file.with_suffix(ext)
                            if alt_file.exists():
                                video_file = alt_file
                                break
                
                if video_file.exists() and video_file.stat().st_size > 0:
                    self._last_successful_parser = parser
                    if progress_callback:
                        progress_callback("下载完成", 90)
                    logger.info(f"✓ {parser} 下载成功: {video_file}")
                    return str(video_file)
                else:
                    logger.warning(f"{parser} 下载的文件不存在或为空")
                    
            except Exception as e:
                last_error = e
                logger.warning(f"✗ {parser} 下载失败: {str(e)[:150]}")
                continue
        
        # 所有下载方案都失败
        error_msg = (
            f"所有下载方案均失败（尝试了 {len(parsers)} 个解析器）\n"
            f"最后错误: {last_error}\n\n"
            "建议：\n"
            "1. 检查链接是否有效\n"
            "2. 确认已安装 FFmpeg（必需）\n"
            "3. 尝试使用 B站/YouTube（更稳定）\n"
            "4. 手动下载后通过'文件导入'上传"
        )
        raise RuntimeError(error_msg)
    
    def download_video_sync(
        self,
        url: str,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> str:
        """同步下载视频（用于线程池）"""
        return asyncio.run(self.download_video(url, progress_callback))


async def get_kuaishou_video_info_videodl(url: str) -> Dict[str, Any]:
    """便捷函数：使用 videodl 获取快手视频信息"""
    import tempfile
    temp_dir = Path(tempfile.mkdtemp(prefix='kuaishou_'))
    try:
        downloader = KuaishouVideoDLDownloader(download_dir=temp_dir)
        return await downloader.get_video_info(url)
    finally:
        # 清理临时目录
        import shutil
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


async def download_kuaishou_video_videodl(
    url: str,
    output_dir: Path,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> str:
    """便捷函数：使用 videodl 下载快手视频"""
    downloader = KuaishouVideoDLDownloader(download_dir=output_dir)
    return await downloader.download_video(url, progress_callback)
