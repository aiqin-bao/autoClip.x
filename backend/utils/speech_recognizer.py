"""
语音识别工具 - 支持多种语音识别服务
支持本地Whisper、OpenAI API、Azure Speech Services等多种语音识别服务
"""
import logging
import subprocess
import json
import os
import asyncio
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
from enum import Enum
import requests
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 尝试导入bcut-asr
try:
    from bcut_asr import BcutASR
    from bcut_asr.orm import ResultStateEnum
    BCUT_ASR_AVAILABLE = True
except ImportError:
    BCUT_ASR_AVAILABLE = False
    logger.warning("bcut-asr未安装，将跳过bcut-asr方法")

def _auto_install_bcut_asr():
    """自动安装bcut-asr"""
    try:
        import subprocess
        import sys
        from pathlib import Path
        
        # 获取安装脚本路径
        script_path = Path(__file__).parent.parent.parent / "scripts" / "install_bcut_asr.py"
        
        if not script_path.exists():
            logger.error("安装脚本不存在，请手动安装bcut-asr")
            _show_manual_install_guide()
            return False
        
        logger.info("开始自动安装bcut-asr...")
        
        # 运行安装脚本
        result = subprocess.run([
            sys.executable, str(script_path)
        ], capture_output=True, text=True, timeout=600)  # 10分钟超时
        
        if result.returncode == 0:
            logger.info("✅ bcut-asr自动安装成功")
            return True
        else:
            logger.error(f"❌ bcut-asr自动安装失败: {result.stderr}")
            _show_manual_install_guide()
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("❌ bcut-asr安装超时")
        _show_manual_install_guide()
        return False
    except Exception as e:
        logger.error(f"❌ bcut-asr自动安装失败: {e}")
        _show_manual_install_guide()
        return False

def _show_manual_install_guide():
    """显示手动安装指导"""
    logger.info("📋 手动安装指导:")
    logger.info("1. 安装 ffmpeg:")
    logger.info("   macOS: brew install ffmpeg")
    logger.info("   Ubuntu: sudo apt install ffmpeg")
    logger.info("   Windows: winget install ffmpeg")
    logger.info("2. 安装 bcut-asr:")
    logger.info("   git clone https://github.com/SocialSisterYi/bcut-asr.git")
    logger.info("   cd bcut-asr && pip install .")
    logger.info("3. 运行手动安装脚本:")
    logger.info("   python scripts/manual_install_guide.py")

def _ensure_bcut_asr_available():
    """确保bcut-asr可用，如果不可用则尝试自动安装"""
    global BCUT_ASR_AVAILABLE
    
    if BCUT_ASR_AVAILABLE:
        return True
    
    logger.info("bcut-asr不可用，尝试自动安装...")
    
    if _auto_install_bcut_asr():
        # 重新尝试导入
        try:
            from bcut_asr import BcutASR
            from bcut_asr.orm import ResultStateEnum
            BCUT_ASR_AVAILABLE = True
            logger.info("✅ bcut-asr安装成功，现在可以使用")
            return True
        except ImportError:
            logger.error("❌ bcut-asr安装后仍无法导入")
            return False
    else:
        logger.warning("⚠️ bcut-asr自动安装失败，将使用其他方法")
        return False


class SpeechRecognitionMethod(str, Enum):
    """语音识别方法枚举"""
    BCUT_ASR = "bcut_asr"
    WHISPER_LOCAL = "whisper_local"
    OPENAI_API = "openai_api"
    AZURE_SPEECH = "azure_speech"
    GOOGLE_SPEECH = "google_speech"
    ALIYUN_SPEECH = "aliyun_speech"


class LanguageCode(str, Enum):
    """支持的语言代码"""
    # 中文
    CHINESE_SIMPLIFIED = "zh"
    CHINESE_TRADITIONAL = "zh-TW"
    # 英文
    ENGLISH = "en"
    ENGLISH_US = "en-US"
    ENGLISH_UK = "en-GB"
    # 日文
    JAPANESE = "ja"
    # 韩文
    KOREAN = "ko"
    # 法文
    FRENCH = "fr"
    # 德文
    GERMAN = "de"
    # 西班牙文
    SPANISH = "es"
    # 俄文
    RUSSIAN = "ru"
    # 阿拉伯文
    ARABIC = "ar"
    # 葡萄牙文
    PORTUGUESE = "pt"
    # 意大利文
    ITALIAN = "it"
    # 自动检测
    AUTO = "auto"


@dataclass
class SpeechRecognitionConfig:
    """语音识别配置"""
    method: SpeechRecognitionMethod = SpeechRecognitionMethod.BCUT_ASR
    language: LanguageCode = LanguageCode.AUTO
    model: str = "base"  # Whisper模型大小
    timeout: int = 0  # 超时时间（秒），0表示无限制
    output_format: str = "srt"  # 输出格式
    enable_timestamps: bool = True  # 是否启用时间戳
    enable_punctuation: bool = True  # 是否启用标点符号
    enable_speaker_diarization: bool = False  # 是否启用说话人分离
    enable_fallback: bool = True  # 是否启用回退机制
    fallback_method: SpeechRecognitionMethod = SpeechRecognitionMethod.WHISPER_LOCAL  # 回退方法
    
    def __post_init__(self):
        """验证配置参数"""
        # 验证方法
        if not isinstance(self.method, SpeechRecognitionMethod):
            try:
                self.method = SpeechRecognitionMethod(self.method)
            except ValueError:
                raise ValueError(f"不支持的语音识别方法: {self.method}")
        
        # 验证语言
        if not isinstance(self.language, LanguageCode):
            try:
                self.language = LanguageCode(self.language)
            except ValueError:
                raise ValueError(f"不支持的语言代码: {self.language}")
        
        # 验证模型
        valid_models = ["tiny", "base", "small", "medium", "large"]
        if self.model not in valid_models:
            raise ValueError(f"不支持的Whisper模型: {self.model}")
        
        # 验证超时时间
        if self.timeout < 0:
            raise ValueError("超时时间不能为负数")
        
        # 验证输出格式
        valid_formats = ["srt", "vtt", "txt", "json"]
        if self.output_format not in valid_formats:
            raise ValueError(f"不支持的输出格式: {self.output_format}")


class SpeechRecognitionError(Exception):
    """语音识别错误"""
    pass


class SpeechRecognizer:
    """语音识别器，支持多种语音识别服务"""
    
    def __init__(self, config: Optional[SpeechRecognitionConfig] = None):
        self.config = config or SpeechRecognitionConfig()
        self.available_methods = self._check_available_methods()
    
    def _check_available_methods(self) -> Dict[SpeechRecognitionMethod, bool]:
        """检查可用的语音识别方法"""
        methods = {}
        
        # 检查bcut-asr
        methods[SpeechRecognitionMethod.BCUT_ASR] = self._check_bcut_asr_availability()
        
        # 检查本地Whisper
        methods[SpeechRecognitionMethod.WHISPER_LOCAL] = self._check_whisper_availability()
        
        # 检查OpenAI API
        methods[SpeechRecognitionMethod.OPENAI_API] = self._check_openai_availability()
        
        # 检查Azure Speech Services
        methods[SpeechRecognitionMethod.AZURE_SPEECH] = self._check_azure_speech_availability()
        
        # 检查Google Speech-to-Text
        methods[SpeechRecognitionMethod.GOOGLE_SPEECH] = self._check_google_speech_availability()
        
        # 检查阿里云语音识别
        methods[SpeechRecognitionMethod.ALIYUN_SPEECH] = self._check_aliyun_speech_availability()
        
        return methods
    
    def _check_bcut_asr_availability(self) -> bool:
        """检查bcut-asr是否可用，如果不可用则尝试自动安装"""
        if BCUT_ASR_AVAILABLE:
            return True
        
        # 尝试自动安装
        logger.info("bcut-asr不可用，尝试自动安装...")
        if _ensure_bcut_asr_available():
            return True
        
        logger.warning("bcut-asr不可用且自动安装失败")
        return False
    
    def _check_whisper_availability(self) -> bool:
        """检查本地Whisper是否可用（faster-whisper 优先，fallback 到 openai-whisper CLI）"""
        try:
            from faster_whisper import WhisperModel  # noqa: F401
            return True
        except ImportError:
            pass
        try:
            result = subprocess.run(['whisper', '--help'],
                                    capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("本地Whisper未安装或不可用")
            return False
    
    def _check_openai_availability(self) -> bool:
        """检查OpenAI API是否可用"""
        api_key = os.getenv("OPENAI_API_KEY")
        return api_key is not None and len(api_key.strip()) > 0
    
    def _check_azure_speech_availability(self) -> bool:
        """检查Azure Speech Services是否可用"""
        api_key = os.getenv("AZURE_SPEECH_KEY")
        region = os.getenv("AZURE_SPEECH_REGION")
        return api_key is not None and region is not None
    
    def _check_google_speech_availability(self) -> bool:
        """检查Google Speech-to-Text是否可用"""
        # 检查Google Cloud凭证文件
        cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_file and Path(cred_file).exists():
            return True
        
        # 检查API密钥
        api_key = os.getenv("GOOGLE_SPEECH_API_KEY")
        return api_key is not None
    
    def _check_aliyun_speech_availability(self) -> bool:
        """检查阿里云语音识别是否可用"""
        access_key = os.getenv("ALIYUN_ACCESS_KEY_ID")
        secret_key = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
        app_key = os.getenv("ALIYUN_SPEECH_APP_KEY")
        return access_key is not None and secret_key is not None and app_key is not None
    
    def _extract_audio_from_video(self, video_path: Path, output_dir: Path) -> Path:
        """
        从视频文件中提取音频
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            
        Returns:
            提取的音频文件路径
        """
        try:
            # 检查ffmpeg是否可用
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise SpeechRecognitionError("ffmpeg不可用，请安装ffmpeg")
            
            # 生成音频文件路径
            audio_filename = f"{video_path.stem}_audio.wav"
            audio_path = output_dir / audio_filename
            
            # 如果音频文件已存在，直接返回
            if audio_path.exists():
                logger.info(f"音频文件已存在: {audio_path}")
                return audio_path
            
            logger.info(f"正在从视频提取音频: {video_path} -> {audio_path}")
            
            # 使用ffmpeg提取音频
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-vn',  # 不处理视频流
                '-acodec', 'pcm_s16le',  # 使用PCM 16位编码
                '-ar', '16000',  # 采样率16kHz
                '-ac', '1',  # 单声道
                '-y',  # 覆盖输出文件
                str(audio_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                raise SpeechRecognitionError(f"音频提取失败: {result.stderr}")
            
            if not audio_path.exists():
                raise SpeechRecognitionError("音频提取失败，输出文件不存在")
            
            logger.info(f"音频提取成功: {audio_path}")
            return audio_path
            
        except subprocess.TimeoutExpired:
            raise SpeechRecognitionError("音频提取超时")
        except Exception as e:
            raise SpeechRecognitionError(f"音频提取失败: {e}")
    
    def generate_subtitle(self, video_path: Path, output_path: Optional[Path] = None, 
                         config: Optional[SpeechRecognitionConfig] = None) -> Path:
        """
        生成字幕文件
        
        Args:
            video_path: 视频文件路径
            output_path: 输出字幕文件路径
            config: 语音识别配置
            
        Returns:
            生成的字幕文件路径
            
        Raises:
            SpeechRecognitionError: 语音识别失败
        """
        if not video_path.exists():
            raise SpeechRecognitionError(f"视频文件不存在: {video_path}")
        
        # 使用传入的配置或默认配置
        config = config or self.config
        
        # 确定输出路径
        if output_path is None:
            output_path = video_path.parent / f"{video_path.stem}.{config.output_format}"
        
        # 根据配置的方法选择识别服务，支持回退机制
        try:
            if config.method == SpeechRecognitionMethod.BCUT_ASR:
                return self._generate_subtitle_bcut_asr(video_path, output_path, config)
            elif config.method == SpeechRecognitionMethod.WHISPER_LOCAL:
                return self._generate_subtitle_whisper_local(video_path, output_path, config)
            elif config.method == SpeechRecognitionMethod.OPENAI_API:
                return self._generate_subtitle_openai_api(video_path, output_path, config)
            elif config.method == SpeechRecognitionMethod.AZURE_SPEECH:
                return self._generate_subtitle_azure_speech(video_path, output_path, config)
            elif config.method == SpeechRecognitionMethod.GOOGLE_SPEECH:
                return self._generate_subtitle_google_speech(video_path, output_path, config)
            elif config.method == SpeechRecognitionMethod.ALIYUN_SPEECH:
                return self._generate_subtitle_aliyun_speech(video_path, output_path, config)
            else:
                raise SpeechRecognitionError(f"不支持的语音识别方法: {config.method}")
        except SpeechRecognitionError as e:
            # 如果启用了回退机制且当前方法不是回退方法，则尝试回退
            if (config.enable_fallback and 
                config.method != config.fallback_method and 
                self.available_methods.get(config.fallback_method, False)):
                
                logger.warning(f"主方法 {config.method} 失败: {e}")
                logger.info(f"尝试回退到 {config.fallback_method}")
                
                # 创建回退配置
                fallback_config = SpeechRecognitionConfig(
                    method=config.fallback_method,
                    language=config.language,
                    model=config.model,
                    timeout=config.timeout,
                    output_format=config.output_format,
                    enable_timestamps=config.enable_timestamps,
                    enable_punctuation=config.enable_punctuation,
                    enable_speaker_diarization=config.enable_speaker_diarization,
                    enable_fallback=False  # 避免无限回退
                )
                
                return self.generate_subtitle(video_path, output_path, fallback_config)
            else:
                raise
    
    def _generate_subtitle_bcut_asr(self, video_path: Path, output_path: Path, 
                                   config: SpeechRecognitionConfig) -> Path:
        """使用bcut-asr生成字幕"""
        # 确保bcut-asr可用
        if not _ensure_bcut_asr_available():
            raise SpeechRecognitionError(
                "bcut-asr不可用且自动安装失败，请手动安装:\n"
                "1. 运行: python scripts/install_bcut_asr.py\n"
                "2. 或手动安装: git clone https://github.com/SocialSisterYi/bcut-asr.git\n"
                "3. 同时确保已安装ffmpeg:\n"
                "   macOS: brew install ffmpeg\n"
                "   Ubuntu: sudo apt install ffmpeg\n"
                "   Windows: winget install ffmpeg"
            )
        
        try:
            logger.info(f"开始使用bcut-asr生成字幕: {video_path}")
            
            # 检查视频文件是否存在
            if not video_path.exists():
                raise SpeechRecognitionError(f"视频文件不存在: {video_path}")
            
            # 检查视频文件大小
            file_size = video_path.stat().st_size
            if file_size == 0:
                raise SpeechRecognitionError(f"视频文件为空: {video_path}")
            
            # 检查文件格式，如果是视频文件需要先提取音频
            audio_path = self._extract_audio_from_video(video_path, output_path.parent)
            
            # 创建BcutASR实例，使用音频文件
            asr = BcutASR(str(audio_path))
            
            # 上传文件
            logger.info("正在上传文件到bcut-asr...")
            asr.upload()
            
            # 创建任务
            logger.info("正在创建识别任务...")
            asr.create_task()
            
            # 轮询检查结果
            logger.info("正在等待识别结果...")
            max_attempts = 60  # 最多等待5分钟（每5秒检查一次）
            attempt = 0
            
            while attempt < max_attempts:
                result = asr.result()
                
                # 判断识别成功
                if result.state == ResultStateEnum.COMPLETE:
                    logger.info("bcut-asr识别完成")
                    break
                elif result.state == ResultStateEnum.FAILED:
                    raise SpeechRecognitionError("bcut-asr识别失败")
                
                # 等待5秒后重试
                import time
                time.sleep(5)
                attempt += 1
                logger.info(f"等待识别结果... ({attempt}/{max_attempts})")
            else:
                raise SpeechRecognitionError("bcut-asr识别超时")
            
            # 解析字幕内容
            subtitle = result.parse()
            
            # 判断是否存在字幕
            if not subtitle.has_data():
                raise SpeechRecognitionError("bcut-asr未识别到有效字幕内容")
            
            # 根据输出格式保存字幕
            if config.output_format == "srt":
                subtitle_content = subtitle.to_srt()
            elif config.output_format == "json":
                subtitle_content = subtitle.to_json()
            elif config.output_format == "lrc":
                subtitle_content = subtitle.to_lrc()
            elif config.output_format == "txt":
                subtitle_content = subtitle.to_txt()
            else:
                # 默认使用srt格式
                subtitle_content = subtitle.to_srt()
            
            # 写入文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(subtitle_content)
            
            logger.info(f"bcut-asr字幕生成成功: {output_path}")
            return output_path
            
        except Exception as e:
            error_msg = f"bcut-asr生成字幕时发生错误: {e}\n"
            error_msg += "可能的原因:\n"
            error_msg += "1. 网络连接问题\n"
            error_msg += "2. 文件格式不支持\n"
            error_msg += "3. 文件过大\n"
            error_msg += "4. bcut-asr服务暂时不可用"
            logger.error(error_msg)
            raise SpeechRecognitionError(error_msg)
    
    def _generate_subtitle_whisper_local(self, video_path: Path, output_path: Path,
                                       config: SpeechRecognitionConfig) -> Path:
        """使用本地 Whisper 生成字幕（faster-whisper 优先，fallback 到 openai-whisper CLI）"""
        if not self.available_methods[SpeechRecognitionMethod.WHISPER_LOCAL]:
            raise SpeechRecognitionError(
                "本地Whisper不可用，请安装：pip install faster-whisper 或 pip install openai-whisper"
            )

        # ── faster-whisper（Python API，速度快 3-4x）──────────────────────────
        try:
            from faster_whisper import WhisperModel
            logger.info(f"使用 faster-whisper 生成字幕: {video_path}")

            device = "cpu"
            compute_type = "int8"
            model_size = config.model if config.model in ("tiny", "base", "small", "medium", "large-v2", "large-v3") else "base"

            model = WhisperModel(model_size, device=device, compute_type=compute_type)

            lang = None if config.language == LanguageCode.AUTO else config.language
            segments, info = model.transcribe(
                str(video_path),
                language=lang,
                beam_size=5,
                vad_filter=True,
            )
            logger.info(f"faster-whisper 检测语言: {info.language} (概率 {info.language_probability:.2f})")

            # 写 SRT
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments, 1):
                    def _fmt(t: float) -> str:
                        h = int(t // 3600)
                        m = int((t % 3600) // 60)
                        s = int(t % 60)
                        ms = int((t - int(t)) * 1000)
                        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                    f.write(f"{i}\n{_fmt(seg.start)} --> {_fmt(seg.end)}\n{seg.text.strip()}\n\n")

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise SpeechRecognitionError("faster-whisper 未生成有效字幕文件")

            logger.info(f"faster-whisper 字幕生成成功: {output_path}")
            return output_path

        except ImportError:
            logger.info("faster-whisper 未安装，fallback 到 openai-whisper CLI")
        except SpeechRecognitionError:
            raise
        except Exception as e:
            logger.warning(f"faster-whisper 失败: {e}，fallback 到 openai-whisper CLI")

        # ── openai-whisper CLI fallback ───────────────────────────────────────
        try:
            logger.info(f"使用 openai-whisper CLI 生成字幕: {video_path}")
            if not video_path.exists():
                raise SpeechRecognitionError(f"视频文件不存在: {video_path}")

            cmd = [
                'whisper', str(video_path),
                '--output_dir', str(output_path.parent),
                '--output_format', config.output_format,
                '--model', config.model,
            ]
            if config.language != LanguageCode.AUTO:
                cmd.extend(['--language', config.language])

            logger.info(f"执行命令: {' '.join(cmd)}")
            run_kwargs = dict(capture_output=True, text=True, cwd=str(video_path.parent))
            if config.timeout > 0:
                run_kwargs['timeout'] = config.timeout

            result = subprocess.run(cmd, **run_kwargs)

            if result.returncode == 0:
                if output_path.exists():
                    logger.info(f"openai-whisper 字幕生成成功: {output_path}")
                    return output_path
                candidates = list(output_path.parent.glob(f"{video_path.stem}*.{config.output_format}"))
                if candidates:
                    logger.info(f"找到输出文件: {candidates[0]}")
                    return candidates[0]
                raise SpeechRecognitionError("Whisper 执行成功但未找到输出文件")
            else:
                raise SpeechRecognitionError(
                    f"openai-whisper 执行失败 (code={result.returncode}): {result.stderr}"
                )
        except subprocess.TimeoutExpired:
            raise SpeechRecognitionError(f"Whisper 执行超时（{config.timeout}秒），建议换用 tiny/base 模型")
        except FileNotFoundError:
            raise SpeechRecognitionError(
                "找不到 whisper 命令，请安装：pip install openai-whisper"
            )
        except SpeechRecognitionError:
            raise
        except Exception as e:
            raise SpeechRecognitionError(f"Whisper 生成字幕失败: {e}")

    def _generate_subtitle_openai_api(self, video_path: Path, output_path: Path,
                                    config: SpeechRecognitionConfig) -> Path:
        """使用OpenAI API生成字幕"""
        if not self.available_methods[SpeechRecognitionMethod.OPENAI_API]:
            raise SpeechRecognitionError("OpenAI API不可用，请设置OPENAI_API_KEY环境变量")
        
        try:
            logger.info(f"开始使用OpenAI API生成字幕: {video_path}")
            
            # 这里需要实现OpenAI API调用
            # 由于需要额外的依赖，这里先抛出异常
            raise SpeechRecognitionError("OpenAI API功能暂未实现，请使用本地Whisper")
            
        except Exception as e:
            error_msg = f"OpenAI API生成字幕时发生错误: {e}"
            logger.error(error_msg)
            raise SpeechRecognitionError(error_msg)
    
    def _generate_subtitle_azure_speech(self, video_path: Path, output_path: Path, 
                                      config: SpeechRecognitionConfig) -> Path:
        """使用Azure Speech Services生成字幕"""
        if not self.available_methods[SpeechRecognitionMethod.AZURE_SPEECH]:
            raise SpeechRecognitionError("Azure Speech Services不可用，请设置AZURE_SPEECH_KEY和AZURE_SPEECH_REGION环境变量")
        
        try:
            logger.info(f"开始使用Azure Speech Services生成字幕: {video_path}")
            
            # 这里需要实现Azure Speech Services调用
            raise SpeechRecognitionError("Azure Speech Services功能暂未实现，请使用本地Whisper")
            
        except Exception as e:
            error_msg = f"Azure Speech Services生成字幕时发生错误: {e}"
            logger.error(error_msg)
            raise SpeechRecognitionError(error_msg)
    
    def _generate_subtitle_google_speech(self, video_path: Path, output_path: Path, 
                                       config: SpeechRecognitionConfig) -> Path:
        """使用Google Speech-to-Text生成字幕"""
        if not self.available_methods[SpeechRecognitionMethod.GOOGLE_SPEECH]:
            raise SpeechRecognitionError("Google Speech-to-Text不可用，请设置GOOGLE_APPLICATION_CREDENTIALS或GOOGLE_SPEECH_API_KEY环境变量")
        
        try:
            logger.info(f"开始使用Google Speech-to-Text生成字幕: {video_path}")
            
            # 这里需要实现Google Speech-to-Text调用
            raise SpeechRecognitionError("Google Speech-to-Text功能暂未实现，请使用本地Whisper")
            
        except Exception as e:
            error_msg = f"Google Speech-to-Text生成字幕时发生错误: {e}"
            logger.error(error_msg)
            raise SpeechRecognitionError(error_msg)
    
    def _generate_subtitle_aliyun_speech(self, video_path: Path, output_path: Path, 
                                       config: SpeechRecognitionConfig) -> Path:
        """使用阿里云语音识别生成字幕"""
        if not self.available_methods[SpeechRecognitionMethod.ALIYUN_SPEECH]:
            raise SpeechRecognitionError("阿里云语音识别不可用，请设置ALIYUN_ACCESS_KEY_ID、ALIYUN_ACCESS_KEY_SECRET和ALIYUN_SPEECH_APP_KEY环境变量")
        
        try:
            logger.info(f"开始使用阿里云语音识别生成字幕: {video_path}")
            
            # 这里需要实现阿里云语音识别调用
            raise SpeechRecognitionError("阿里云语音识别功能暂未实现，请使用本地Whisper")
            
        except Exception as e:
            error_msg = f"阿里云语音识别生成字幕时发生错误: {e}"
            logger.error(error_msg)
            raise SpeechRecognitionError(error_msg)
    
    def get_available_methods(self) -> Dict[SpeechRecognitionMethod, bool]:
        """获取可用的语音识别方法"""
        return self.available_methods.copy()
    
    def get_supported_languages(self) -> List[LanguageCode]:
        """获取支持的语言列表"""
        return list(LanguageCode)
    
    def get_whisper_models(self) -> List[str]:
        """获取可用的Whisper模型列表"""
        return ["tiny", "base", "small", "medium", "large"]


def generate_subtitle_for_video(video_path: Path, output_path: Optional[Path] = None, 
                               method: str = "auto", language: str = "auto", 
                               model: str = "base", enable_fallback: bool = True) -> Path:
    """
    为视频生成字幕文件的便捷函数
    
    Args:
        video_path: 视频文件路径
        output_path: 输出字幕文件路径
        method: 生成方法 ("auto", "bcut_asr", "whisper_local", "openai_api", "azure_speech", "google_speech", "aliyun_speech")
        language: 语言代码
        model: Whisper模型大小（仅对whisper_local有效）
        enable_fallback: 是否启用回退机制
        
    Returns:
        生成的字幕文件路径
        
    Raises:
        SpeechRecognitionError: 语音识别失败
    """
    # 创建配置
    config = SpeechRecognitionConfig(
        method=SpeechRecognitionMethod(method) if method != "auto" else SpeechRecognitionMethod.BCUT_ASR,
        language=LanguageCode(language),
        model=model,
        enable_fallback=enable_fallback
    )
    
    recognizer = SpeechRecognizer()
    
    if method == "auto":
        # 自动选择最佳方法
        available_methods = recognizer.get_available_methods()
        
        # 按优先级选择方法（bcut-asr优先，因为速度更快）
        priority_methods = [
            SpeechRecognitionMethod.BCUT_ASR,
            SpeechRecognitionMethod.WHISPER_LOCAL,
            SpeechRecognitionMethod.OPENAI_API,
            SpeechRecognitionMethod.AZURE_SPEECH,
            SpeechRecognitionMethod.GOOGLE_SPEECH,
            SpeechRecognitionMethod.ALIYUN_SPEECH
        ]
        
        for priority_method in priority_methods:
            if available_methods.get(priority_method, False):
                config.method = priority_method
                break
        else:
            raise SpeechRecognitionError("没有可用的语音识别服务，请安装whisper或配置API密钥")
    
    return recognizer.generate_subtitle(video_path, output_path, config)


def get_available_speech_recognition_methods() -> Dict[str, bool]:
    """
    获取可用的语音识别方法
    
    Returns:
        可用方法字典
    """
    recognizer = SpeechRecognizer()
    available_methods = recognizer.get_available_methods()
    
    return {
        method.value: available 
        for method, available in available_methods.items()
    }


def get_supported_languages() -> List[str]:
    """
    获取支持的语言列表
    
    Returns:
        支持的语言代码列表
    """
    return [lang.value for lang in LanguageCode]


def get_whisper_models() -> List[str]:
    """
    获取可用的Whisper模型列表
    
    Returns:
        Whisper模型列表
    """
    return ["tiny", "base", "small", "medium", "large"]
