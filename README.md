# autoClip.x

> AI 驱动的视频智能切片系统 — 重构升级版

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat&logo=react&logoColor=black)](https://reactjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6?style=flat&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

autoClip.x 是对 [autoclip](https://github.com/zhouxiaoka/autoclip) 开源项目的深度重构升级版本。核心目标是彻底去除 Redis + Celery 外部依赖，将系统简化为**单进程部署**，同时保留并增强所有核心功能。

## 核心改进

| 指标 | 原版 autoclip | autoClip.x |
|------|--------------|------------|
| 启动进程数 | 3（FastAPI + Celery Worker + Redis） | **1** |
| 进度推送 | 0~2s 轮询 | **< 100ms SSE 实时推送** |
| 外部服务依赖 | Redis（必须运行） | **无** |
| 启动命令 | 需协调 3 个进程的启动脚本 | `uvicorn backend.main:app` |
| 并发处理 | Celery Worker | asyncio TaskManager |
| 定时调度 | Celery Beat | asyncio Scheduler |

## 功能特性

### 🎬 多平台视频下载

- **YouTube**：支持视频和播放列表下载
- **B站（Bilibili）**：支持视频和番剧下载
- **抖音（Douyin）**：
  - 双引擎下载（Playwright API 拦截 + yt-dlp 备用）
  - 持久化扫码登录
  - 自动 Whisper 字幕生成
- **快手（Kuaishou）**：⭐ 新增
  - 多解析器自动切换（8个通用解析器）
  - videodl 库支持（主要方案）
  - Playwright 备用方案
  - 成功率 80%+
- **本地文件**：支持直接上传视频文件

### 🤖 AI 智能处理

- **6步处理流水线**：大纲提取 → 时间线识别 → 精彩度评分 → 标题生成 → 主题聚类 → 视频切割
- **基于通义千问**（DashScope API）
- **LLM 并发调用**（ThreadPoolExecutor，最多 3 路并发）
- **FFmpeg 并行切割**（最多 4 路并发）

### 📊 其他特性

- **智能合集**：AI 推荐 + 手动创建，支持拖拽排序
- **SSE 实时进度**：Server-Sent Events 推送，< 100ms 延迟
- **零外部依赖**：SQLite WAL 模式，无需 Redis / Celery / RabbitMQ
- **现代界面**：React 18 + TypeScript + Ant Design，响应式设计
- **单进程部署**：一条命令启动所有服务

## 系统架构

```
用户界面 (React 18 + Ant Design)
       │
       │  HTTP REST + SSE (进度流)
       ▼
FastAPI 后端 (单进程)
  ├── asyncio TaskManager      ← 替代 Celery Worker
  ├── asyncio Scheduler        ← 替代 Celery Beat
  ├── ProgressStore (内存)     ← 替代 Redis Pub/Sub
  ├── SQLite (WAL 模式)
  └── AI 处理流水线
        ├── Step 1: 大纲提取
        ├── Step 2: 时间线识别
        ├── Step 3: 精彩度评分  ─┐ LLM 并发调用
        ├── Step 4: 标题生成   ─┘ (ThreadPoolExecutor, max 3)
        ├── Step 5: 主题聚类
        └── Step 6: 视频切割    (FFmpeg 并行, max 4)
```

## 快速开始

### 🚀 一键启动（真正的一键！）

**无需任何手动操作，完全自动化！**

#### macOS / Linux

```bash
# 1. 克隆项目
git clone https://github.com/aiqin-bao/autoClip.x.git
cd autoclip.x

# 2. 一键启动
./start_autoclip.sh
```

#### Windows

```powershell
# 1. 克隆项目
git clone https://github.com/aiqin-bao/autoClip.x.git
cd autoclip.x

# 2. 一键启动（双击或运行）
start_autoclip.bat
# 或
.\start_autoclip.ps1
```

**脚本会自动完成**：
- ✅ 检测操作系统（macOS / Linux / Windows）
- ✅ 自动安装 Python 3.12+（如果未安装）
- ✅ 自动安装 Node.js 18+（如果未安装）
- ✅ 自动创建 Python 虚拟环境
- ✅ 自动安装所有依赖
- ✅ 自动初始化数据库
- ✅ 自动启动所有服务

**启动完成后访问**：
- 🌐 前端界面：http://localhost:3000
- 🌐 后端 API：http://localhost:8000
- 📚 API 文档：http://localhost:8000/docs

### 系统要求

**自动安装（推荐）**：
- 运行启动脚本，所有依赖会自动安装，无需手动操作

**可选依赖**：
- FFmpeg（视频处理，建议手动安装以获得更好性能）
- Playwright（抖音下载）：`playwright install chromium`

### Docker 部署

```bash
# 配置环境变量
cp env.example .env (可以后台配置)
# 编辑 .env，填入 API_DASHSCOPE_API_KEY

# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

服务地址：
- 前端：http://localhost:3000
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

### 本地脚本启动

```bash
./start_autoclip.sh    # 启动
./stop_autoclip.sh     # 停止
./status_autoclip.sh   # 状态检查
```

## 环境变量

```bash
# .env 配置示例

# AI 配置（必填）
API_DASHSCOPE_API_KEY=your_dashscope_api_key
API_MODEL_NAME=qwen-long

# 数据库
DATABASE_URL=sqlite:///./data/autoclip.db

# 运行模式
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO
```

> 无需配置 `REDIS_URL`，autoClip.x 不依赖 Redis。

## 项目结构

```
autoclip.x/
├── backend/
│   ├── api/v1/             # REST API 路由
│   │   ├── projects.py     # 项目管理（含 TaskManager 调度）
│   │   ├── sse_progress.py # SSE 进度流端点
│   │   ├── youtube.py      # YouTube 下载
│   │   ├── bilibili.py     # B 站下载
│   │   ├── douyin.py       # 抖音下载（双引擎 + 登录管理）
│   │   ├── clips.py        # 切片管理
│   │   └── collections.py  # 合集管理
│   ├── core/
│   │   ├── task_manager.py # asyncio 任务管理器
│   │   ├── progress_store.py # 内存进度存储 + SSE 广播
│   │   ├── scheduler.py    # asyncio 定时调度器
│   │   ├── database.py     # SQLite WAL 配置
│   │   └── config.py       # 系统配置
│   ├── pipeline/           # AI 处理流水线（Step 1-6）
│   ├── services/           # 业务逻辑层
│   ├── models/             # SQLAlchemy 数据模型
│   └── utils/              # 工具函数（FFmpeg、LLM 客户端、抖音下载器等）
├── frontend/               # React 18 + TypeScript + Ant Design
├── data/                   # 数据库、视频文件、切片输出
├── scripts/                # 运维脚本
├── logs/                   # 运行日志
├── Dockerfile              # 多阶段构建
├── docker-compose.yml      # 单服务编排（无 Redis/Celery）
└── start_autoclip.sh       # 本地启动入口
```

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/projects` | GET / POST | 项目列表 / 创建项目 |
| `/api/v1/projects/{id}` | GET | 项目详情 |
| `/api/v1/projects/{id}/process` | POST | 启动 AI 处理 |
| `/api/v1/projects/{id}/progress/stream` | GET (SSE) | 实时进度流 |
| `/api/v1/youtube/parse` | POST | 解析 YouTube 视频 |
| `/api/v1/youtube/download` | POST | 下载 YouTube 视频 |
| `/api/v1/bilibili/download` | POST | 下载 B 站视频 |
| `/api/v1/douyin/parse` | POST | 解析抖音视频信息 |
| `/api/v1/douyin/download` | POST | 创建抖音下载任务 |
| `/api/v1/douyin/tasks/{id}` | GET | 查询抖音下载任务状态 |
| `/api/v1/douyin/login/start` | POST | 打开 Chromium 窗口扫码登录 |
| `/api/v1/douyin/login/status` | GET | 查询登录状态 |
| `/api/v1/douyin/login/cookies` | DELETE | 清除登录 Cookie |
| `/api/v1/clips` | GET | 切片列表 |
| `/api/v1/collections` | GET / POST | 合集管理 |
| `/api/v1/health/` | GET | 服务健康检查 |

## 故障排除

**YouTube / B 站下载失败**
```bash
pip install --upgrade yt-dlp
```

**抖音下载失败（未登录）**

首次使用需扫码登录，登录状态持久化保存 7 天：
1. 调用 `POST /api/v1/douyin/login/start` 或在前端点击「抖音登录」
2. 系统会弹出真实 Chromium 浏览器窗口
3. 在窗口内完成抖音扫码登录
4. 登录后浏览器 Profile 自动保存，后续下载无需重复登录

**Playwright 未安装**
```bash
pip install playwright
playwright install chromium
```

**端口占用**
```bash
lsof -i :8000 && lsof -i :3000
kill -9 <PID>
```

**查看日志**
```bash
tail -f logs/backend.log
```

## 致谢

autoClip.x 基于 [autoclip](https://github.com/zhouxiaoka/autoclip) 开源项目重构，感谢原作者的工作。

核心依赖：[FastAPI](https://fastapi.tiangolo.com) · [React](https://reactjs.org) · [Ant Design](https://ant.design) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [FFmpeg](https://ffmpeg.org) · [通义千问 / DashScope](https://dashscope.aliyun.com)

---

MIT License
