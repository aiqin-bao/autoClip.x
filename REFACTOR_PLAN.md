# AutoClip 架构重构计划

> 目标：去掉 Redis + Celery 外部依赖，清理技术债，简化为单进程部署。  
> 当前状态：需要同时运行 FastAPI + Celery Worker + Redis 三个进程。  
> 目标状态：只需 `uvicorn backend.main:app` 一条命令启动。

---

## 阶段一：清理死代码（无破坏性，可独立执行）

### 1A. 直接删除（无任何引用）

| 文件 | 说明 |
|------|------|
| `backend/core/celery_app_fixed.py` | Celery 冗余配置 #2 |
| `backend/core/celery_minimal.py` | Celery 冗余配置 #3 |
| `backend/core/celery_simple_fixed.py` | Celery 冗余配置 #4 |
| `backend/core/unified_config.py` | 重复的配置管理，无引用 |
| `backend/core/unified_paths.py` | 重复的路径工具，无引用 |
| `backend/core/unified_storage.py` | 重复的存储工具，无引用 |
| `backend/shared/progress_publisher.py` | Redis Pub/Sub 路径 B，已废弃 |
| `backend/shared/progress_channels.py` | 配套频道工具，已废弃 |
| `backend/services/enhanced_progress_service.py` | 旧版进度服务 #1 |
| `backend/services/progress_snapshot_service.py` | 旧版进度服务 #2 |
| `backend/services/progress_event_service.py` | 旧版进度服务 #3 |
| `backend/services/progress_message_adapter.py` | 旧版进度服务 #4 |
| `backend/services/progress_update_service.py` | 旧版进度服务 #5 |
| `backend/services/pipeline_adapter.py` | 旧版流水线适配器（590行），已被 simple_pipeline_adapter 替代 |
| `backend/services/processing_orchestrator.py` | 旧版编排器，只被废弃的 processing_service 引用 |
| `backend/services/processing_context.py` | 旧版上下文，只被废弃的 processing_service 引用 |
| `backend/api/v1/websocket.py` | WebSocket 路由，已注释禁用 |
| `backend/services/websocket_gateway_service.py` | WS 网关服务，main.py 中已注释 |
| `backend/scripts/start_celery.py` | Celery 启动脚本（阶段二完成后删除） |

### 1B. 需要小改动后删除

| 目标 | 需要做的修改 |
|------|-------------|
| 删除 `services/websocket_notification_service.py` | 修改 `tasks/processing.py`：移除 import 和所有 `run_async_notification` 调用；修改 `api/v1/projects.py`：移除 import 和两处 `Depends(get_websocket_service)`；修改 `tasks/notification.py`：移除 import |
| 删除 `core/websocket_manager.py` | 等 `websocket_notification_service.py` 删除后执行 |
| 删除 `services/processing_service.py` | 仅被 `api/v1/projects.py` 中旧的 `/process` 端点引用（阶段二重写该端点后执行） |
| 删除 `services/task_queue_service.py` | 完全的 Celery 封装层，阶段二后删除 |
| 删除 `services/task_submission_service.py` | 同上 |
| 删除 `tasks/` 整个目录 | 阶段二完成后，所有 Celery task 文件全部删除 |

---

## 阶段二：核心架构替换（去掉 Redis + Celery）

### 新增文件

| 文件 | 内容 |
|------|------|
| `backend/core/task_manager.py` | asyncio 任务管理器（替代 Celery Worker） |
| `backend/core/progress_store.py` | 内存进度存储 + SSE 事件广播（替代 Redis progress） |
| `backend/api/v1/sse_progress.py` | SSE 进度流端点（替代 simple_progress.py 轮询） |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/core/database.py` | 开启 SQLite WAL 模式（提升并发读写性能） |
| `backend/main.py` | startup 启动 TaskManager；shutdown 优雅关闭；移除 Celery 相关 |
| `backend/api/v1/projects.py` | 将 `process_video_pipeline.delay()` 改为 `task_manager.submit()`；移除所有 Celery/WebSocket 依赖 |
| `backend/services/simple_pipeline_adapter.py` | 将 `emit_progress()` 改为 `progress_store.emit()` |
| `backend/api/v1/__init__.py` | 注册 SSE 进度路由，移除已删除路由的注册 |
| `frontend/src/services/api.ts` | 进度从 axios 轮询改为 EventSource SSE |
| `frontend/src/store/` (进度相关) | 适配 SSE 事件格式 |

### 删除文件

| 文件 | 说明 |
|------|------|
| `backend/core/celery_app.py` | 唯一的 Celery 配置 |
| `backend/services/simple_progress.py` | Redis 版进度服务（被 progress_store.py 替代） |
| `backend/api/v1/simple_progress.py` | 轮询端点（被 SSE 端点替代） |

---

## 阶段三：进一步优化（可选）

| 优化点 | 方案 |
|--------|------|
| LLM 并发调用 | Step1 按块切分后，多块可并发调用（asyncio.gather） |
| SQLite 性能 | 已在阶段二开启 WAL 模式；如并发增大可换 PostgreSQL |
| ffmpeg 并行 | Step6 多个片段可用 ThreadPoolExecutor 并行切割 |
| 前端状态管理 | 将散落的进度轮询 useEffect 统一到 Zustand store |

---

## 改造后效果对比

| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| 启动进程数 | 3（FastAPI + Celery + Redis） | **1** |
| 进度推送延迟 | 0~2秒（轮询） | **<100ms（SSE推送）** |
| backend/ 文件数 | ~115 个 .py 文件 | **~80 个** |
| 外部服务依赖 | Redis（必须运行） | **无** |
| 部署命令 | 需要启动脚本协调3个进程 | `uvicorn backend.main:app` |
| 代码可读性 | 差（4套Celery配置，5套进度服务） | **清晰** |

---

## 执行状态

- [x] 计划文档编写
- [x] **阶段一A**：删除纯死代码文件（18个文件已删除）
- [x] **阶段一B**：清理死代码引用（修改 tasks/processing.py、tasks/notification.py、api/v1/projects.py、services/processing_service.py；新增 progress_update_service 存根）
- [x] **阶段二**：新增 TaskManager（core/task_manager.py）+ ProgressStore（core/progress_store.py）+ SSE 端点（api/v1/sse_progress.py）
- [x] **阶段二**：修改 projects.py（.delay() → task_manager.submit()）/ main.py（TaskManager 生命周期）/ simple_pipeline_adapter.py（Redis→ProgressStore）
- [x] **阶段二**：simple_progress.py API 改用 ProgressStore（不再依赖 Redis）；SQLite 开启 WAL 模式
- [x] **阶段二**：前端 SSE 适配（useSimpleProgressStore 增加 subscribeSSE；SimpleProgressBar 升级为 SSE 优先）
- [x] **阶段二（完成）**：彻底删除 Celery 相关文件（celery_app.py、tasks/ 里的 Celery 任务包装），upload/bilibili/account-health 全部改为 task_manager；新增 asyncio 调度器（core/scheduler.py）替代 Celery beat
- [x] **阶段三**：Step 3/4 LLM 并发（ThreadPoolExecutor，最多 3 并发）+ Step 6 ffmpeg 并行切割（最多 4 并发）
