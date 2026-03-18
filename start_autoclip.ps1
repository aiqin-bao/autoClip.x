# AutoClip.x Windows 启动脚本 (PowerShell)
# 版本: 2.0
# 功能: 启动完整的AutoClip系统（后端API + 前端界面）

# 设置错误处理
$ErrorActionPreference = "Stop"

# =============================================================================
# 配置区域
# =============================================================================

$BACKEND_PORT = 8000
$FRONTEND_PORT = 3000

$BACKEND_STARTUP_TIMEOUT = 60
$FRONTEND_STARTUP_TIMEOUT = 90

$LOG_DIR = "logs"
$BACKEND_LOG = "$LOG_DIR\backend.log"
$FRONTEND_LOG = "$LOG_DIR\frontend.log"

# =============================================================================
# 颜色定义
# =============================================================================

function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Type = "Info"
    )
    
    switch ($Type) {
        "Success" { Write-Host "✅ $Message" -ForegroundColor Green }
        "Error"   { Write-Host "❌ $Message" -ForegroundColor Red }
        "Warning" { Write-Host "⚠️  $Message" -ForegroundColor Yellow }
        "Info"    { Write-Host "ℹ️  $Message" -ForegroundColor Blue }
        "Header"  { 
            Write-Host "`n🚀 $Message" -ForegroundColor Magenta
            Write-Host ("=" * 50) -ForegroundColor Magenta
        }
        "Step"    { Write-Host "`n⚙️  $Message" -ForegroundColor Cyan }
        default   { Write-Host $Message }
    }
}

# =============================================================================
# 工具函数
# =============================================================================

function Test-CommandExists {
    param([string]$Command)
    try {
        if (Get-Command $Command -ErrorAction SilentlyContinue) {
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

function Test-PortInUse {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -ne $connection
}

function Wait-ForService {
    param(
        [string]$Url,
        [int]$Timeout,
        [string]$ServiceName
    )
    
    Write-ColorOutput "等待 $ServiceName 启动..." "Info"
    
    for ($i = 1; $i -le $Timeout; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-ColorOutput "$ServiceName 已启动" "Success"
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    
    Write-ColorOutput "$ServiceName 启动超时" "Error"
    return $false
}

# =============================================================================
# 安装辅助函数
# =============================================================================

function Install-Chocolatey {
    Write-ColorOutput "安装 Chocolatey" "Step"
    Write-ColorOutput "Chocolatey 是 Windows 的包管理器，用于安装 Python 和 Node.js" "Info"
    
    if (Test-CommandExists "choco") {
        Write-ColorOutput "Chocolatey 已安装" "Success"
        return $true
    }
    
    Write-ColorOutput "Chocolatey 未安装，正在自动安装..." "Warning"
    Write-ColorOutput "正在安装 Chocolatey..." "Info"
    Write-ColorOutput "需要管理员权限，请在弹出的窗口中确认" "Warning"
    
    try {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        
        # 刷新环境变量
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Test-CommandExists "choco") {
            Write-ColorOutput "Chocolatey 安装成功" "Success"
            return $true
        } else {
            Write-ColorOutput "Chocolatey 安装失败，请手动安装: https://chocolatey.org/install" "Error"
            return $false
        }
    } catch {
        Write-ColorOutput "Chocolatey 安装失败: $_" "Error"
        Write-ColorOutput "请手动安装: https://chocolatey.org/install" "Error"
        return $false
    }
}

function Install-Python {
    Write-ColorOutput "安装 Python" "Step"
    
    if (Test-CommandExists "python") {
        $pythonVersion = python --version 2>&1
        Write-ColorOutput "Python 已安装 ($pythonVersion)" "Success"
        return $true
    }
    
    Write-ColorOutput "Python 未安装，正在自动安装..." "Warning"
    
    # 检查是否有 Chocolatey
    if (-not (Test-CommandExists "choco")) {
        if (-not (Install-Chocolatey)) {
            Write-ColorOutput "无法安装 Chocolatey，请手动安装 Python" "Error"
            Write-Host "`n手动安装指南:" -ForegroundColor Cyan
            Write-Host "  Chocolatey: choco install python -y"
            Write-Host "  官网:       https://www.python.org/downloads/"
            Write-Host "  注意:       安装时勾选 'Add Python to PATH'"
            return $false
        }
    }
    
    Write-ColorOutput "正在通过 Chocolatey 安装 Python..." "Info"
    Write-ColorOutput "需要管理员权限，请在弹出的窗口中确认" "Warning"
    
    try {
        Start-Process -FilePath "choco" -ArgumentList "install", "python", "-y" -Verb RunAs -Wait
        
        # 刷新环境变量
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Test-CommandExists "python") {
            Write-ColorOutput "Python 安装成功" "Success"
            return $true
        } else {
            Write-ColorOutput "Python 安装失败，请重新打开 PowerShell 或手动安装" "Error"
            Write-Host "`n手动安装指南:" -ForegroundColor Cyan
            Write-Host "  官网: https://www.python.org/downloads/"
            Write-Host "  注意: 安装时勾选 'Add Python to PATH'"
            return $false
        }
    } catch {
        Write-ColorOutput "Python 安装失败: $_" "Error"
        Write-Host "`n手动安装指南:" -ForegroundColor Cyan
        Write-Host "  官网: https://www.python.org/downloads/"
        return $false
    }
}

function Install-NodeJS {
    Write-ColorOutput "安装 Node.js" "Step"
    
    if ((Test-CommandExists "node") -and (Test-CommandExists "npm")) {
        $nodeVersion = node --version
        Write-ColorOutput "Node.js 已安装 ($nodeVersion)" "Success"
        return $true
    }
    
    Write-ColorOutput "Node.js 未安装，正在自动安装..." "Warning"
    
    # 检查是否有 Chocolatey
    if (-not (Test-CommandExists "choco")) {
        if (-not (Install-Chocolatey)) {
            Write-ColorOutput "无法安装 Chocolatey，请手动安装 Node.js" "Error"
            Write-Host "`n手动安装指南:" -ForegroundColor Cyan
            Write-Host "  Chocolatey: choco install nodejs-lts -y"
            Write-Host "  官网:       https://nodejs.org/"
            return $false
        }
    }
    
    Write-ColorOutput "正在通过 Chocolatey 安装 Node.js..." "Info"
    Write-ColorOutput "需要管理员权限，请在弹出的窗口中确认" "Warning"
    
    try {
        Start-Process -FilePath "choco" -ArgumentList "install", "nodejs-lts", "-y" -Verb RunAs -Wait
        
        # 刷新环境变量
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if ((Test-CommandExists "node") -and (Test-CommandExists "npm")) {
            Write-ColorOutput "Node.js 安装成功" "Success"
            return $true
        } else {
            Write-ColorOutput "Node.js 安装失败，请重新打开 PowerShell 或手动安装" "Error"
            Write-Host "`n手动安装指南:" -ForegroundColor Cyan
            Write-Host "  官网: https://nodejs.org/"
            return $false
        }
    } catch {
        Write-ColorOutput "Node.js 安装失败: $_" "Error"
        Write-Host "`n手动安装指南:" -ForegroundColor Cyan
        Write-Host "  官网: https://nodejs.org/"
        return $false
    }
}

function New-VirtualEnvironment {
    Write-ColorOutput "创建 Python 虚拟环境" "Step"
    
    if (Test-Path "venv") {
        Write-ColorOutput "虚拟环境已存在" "Success"
        return $true
    }
    
    Write-ColorOutput "虚拟环境不存在，正在自动创建..." "Warning"
    Write-ColorOutput "正在创建虚拟环境..." "Info"
    
    try {
        python -m venv venv
        
        if (Test-Path "venv") {
            Write-ColorOutput "虚拟环境创建成功" "Success"
            return $true
        } else {
            Write-ColorOutput "虚拟环境创建失败" "Error"
            Write-Host "`n手动创建虚拟环境:" -ForegroundColor Cyan
            Write-Host "  python -m venv venv"
            return $false
        }
    } catch {
        Write-ColorOutput "虚拟环境创建失败: $_" "Error"
        Write-Host "`n手动创建虚拟环境:" -ForegroundColor Cyan
        Write-Host "  python -m venv venv"
        return $false
    }
}

# =============================================================================
# 环境检查函数
# =============================================================================

function Test-Environment {
    Write-ColorOutput "环境检查" "Header"
    
    Write-ColorOutput "检测到 Windows 系统" "Success"
    Write-ColorOutput "PowerShell 版本: $($PSVersionTable.PSVersion)" "Info"
    
    # 检查并安装 Python
    if (-not (Test-CommandExists "python")) {
        Write-ColorOutput "Python 未安装" "Warning"
        if (-not (Install-Python)) {
            Write-ColorOutput "Python 安装失败，无法继续" "Error"
            Write-Host "`n手动安装指南:" -ForegroundColor Cyan
            Write-Host "  Chocolatey: choco install python -y"
            Write-Host "  官网:       https://www.python.org/downloads/"
            Write-Host "  注意:       安装时勾选 'Add Python to PATH'"
            exit 1
        }
    } else {
        $pythonVersion = python --version 2>&1
        Write-ColorOutput "Python 已安装 ($pythonVersion)" "Success"
    }
    
    # 检查并安装 Node.js
    if (-not ((Test-CommandExists "node") -and (Test-CommandExists "npm"))) {
        Write-ColorOutput "Node.js 未安装" "Warning"
        if (-not (Install-NodeJS)) {
            Write-ColorOutput "Node.js 安装失败，无法继续" "Error"
            Write-Host "`n手动安装指南:" -ForegroundColor Cyan
            Write-Host "  Chocolatey: choco install nodejs-lts -y"
            Write-Host "  官网:       https://nodejs.org/"
            exit 1
        }
    } else {
        $nodeVersion = node --version
        $npmVersion = npm --version
        Write-ColorOutput "Node.js 已安装 ($nodeVersion)" "Success"
        Write-ColorOutput "npm 已安装 ($npmVersion)" "Success"
    }
    
    # 检查并创建虚拟环境
    if (-not (Test-Path "venv")) {
        Write-ColorOutput "虚拟环境不存在" "Warning"
        if (-not (New-VirtualEnvironment)) {
            Write-ColorOutput "虚拟环境创建失败，无法继续" "Error"
            Write-Host "`n手动创建虚拟环境:" -ForegroundColor Cyan
            Write-Host "  python -m venv venv"
            exit 1
        }
    } else {
        Write-ColorOutput "虚拟环境存在" "Success"
    }
    
    # 检查项目结构
    $requiredDirs = @("backend", "frontend", "data")
    foreach ($dir in $requiredDirs) {
        if (Test-Path $dir) {
            Write-ColorOutput "目录 $dir 存在" "Success"
        } else {
            Write-ColorOutput "目录 $dir 不存在" "Error"
            exit 1
        }
    }
}

# =============================================================================
# 服务启动函数
# =============================================================================

function Initialize-Environment {
    Write-ColorOutput "设置环境" "Step"
    
    # 创建日志目录
    if (-not (Test-Path $LOG_DIR)) {
        New-Item -ItemType Directory -Path $LOG_DIR | Out-Null
    }
    
    # 激活虚拟环境
    Write-ColorOutput "激活虚拟环境..." "Info"
    & ".\venv\Scripts\Activate.ps1"
    
    # 加载环境变量
    if (Test-Path ".env") {
        Write-ColorOutput "加载环境变量..." "Info"
        Get-Content ".env" | ForEach-Object {
            if ($_ -match "^([^=]+)=(.*)$") {
                [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
        Write-ColorOutput "环境变量加载成功" "Success"
    } else {
        Write-ColorOutput ".env 文件不存在，使用默认配置" "Warning"
        # 创建默认环境变量文件
        if (-not (Test-Path ".env")) {
            Write-ColorOutput "创建默认 .env 文件..." "Info"
            @"
# AutoClip 环境配置
DATABASE_URL=sqlite:///./data/autoclip.db
API_DASHSCOPE_API_KEY=
API_MODEL_NAME=qwen-plus
LOG_LEVEL=INFO
ENVIRONMENT=development
DEBUG=true
"@ | Out-File -FilePath ".env" -Encoding UTF8
            Write-ColorOutput "已创建默认 .env 文件" "Success"
        }
    }
    
    # 检查Python依赖
    Write-ColorOutput "检查 Python 依赖..." "Info"
    try {
        python -c "import fastapi, sqlalchemy" 2>$null
        Write-ColorOutput "Python 依赖检查完成" "Success"
    } catch {
        Write-ColorOutput "缺少依赖，正在安装..." "Warning"
        pip install -r requirements.txt
    }
}

function Initialize-Database {
    Write-ColorOutput "初始化数据库" "Step"
    
    # 确保数据目录存在
    if (-not (Test-Path "data")) {
        New-Item -ItemType Directory -Path "data" | Out-Null
    }
    
    # 初始化数据库
    Write-ColorOutput "创建数据库表..." "Info"
    $initScript = @"
import sys
sys.path.insert(0, '.')
from backend.core.database import engine, Base
from backend.models import project, task, clip, collection, bilibili
try:
    Base.metadata.create_all(bind=engine)
    print('数据库表创建成功')
except Exception as e:
    print(f'数据库初始化失败: {e}')
    sys.exit(1)
"@
    
    $result = python -c $initScript 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-ColorOutput "数据库初始化成功" "Success"
    } else {
        Write-ColorOutput "数据库初始化失败" "Error"
        Write-ColorOutput $result "Error"
        exit 1
    }
}

function Start-Backend {
    Write-ColorOutput "启动后端 API 服务" "Step"
    
    # 检查端口占用
    if (Test-PortInUse -Port $BACKEND_PORT) {
        Write-ColorOutput "端口 $BACKEND_PORT 已被占用，正在自动停止占用进程..." "Warning"
        try {
            Get-NetTCPConnection -LocalPort $BACKEND_PORT -ErrorAction SilentlyContinue | ForEach-Object {
                Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
            Write-ColorOutput "已停止占用端口的进程" "Success"
        } catch {
            Write-ColorOutput "无法自动停止进程，请手动处理" "Warning"
        }
    }
    
    Write-ColorOutput "启动后端服务 (端口: $BACKEND_PORT)..." "Info"
    Write-ColorOutput "注意: 系统使用内置 asyncio TaskManager，无需外部 Worker" "Info"
    
    # 启动后端（新窗口）
    $backendCmd = "python -m uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "& {$backendCmd}" -WindowStyle Normal
    
    # 等待后端启动
    if (Wait-ForService -Url "http://localhost:$BACKEND_PORT/api/v1/health/" -Timeout $BACKEND_STARTUP_TIMEOUT -ServiceName "后端服务") {
        Write-ColorOutput "后端服务已启动" "Success"
        Write-ColorOutput "内置 TaskManager 和 Scheduler 已自动启动" "Success"
    } else {
        Write-ColorOutput "后端服务启动失败" "Error"
        Write-ColorOutput "查看日志: Get-Content $BACKEND_LOG -Tail 50" "Info"
        exit 1
    }
}

function Start-Frontend {
    Write-ColorOutput "启动前端服务" "Step"
    
    # 检查端口占用
    if (Test-PortInUse -Port $FRONTEND_PORT) {
        Write-ColorOutput "端口 $FRONTEND_PORT 已被占用，正在自动停止占用进程..." "Warning"
        try {
            Get-NetTCPConnection -LocalPort $FRONTEND_PORT -ErrorAction SilentlyContinue | ForEach-Object {
                Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
            Write-ColorOutput "已停止占用端口的进程" "Success"
        } catch {
            Write-ColorOutput "无法自动停止进程，请手动处理" "Warning"
        }
    }
    
    # 进入前端目录
    Push-Location frontend
    
    # 检查前端依赖
    if (-not (Test-Path "node_modules")) {
        Write-ColorOutput "安装前端依赖..." "Info"
        npm install
    }
    
    Write-ColorOutput "启动前端服务 (端口: $FRONTEND_PORT)..." "Info"
    
    # 启动前端（新窗口）
    $frontendCmd = "npm run dev -- --host 0.0.0.0 --port $FRONTEND_PORT"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "& {$frontendCmd}" -WindowStyle Normal
    
    # 返回项目根目录
    Pop-Location
    
    # 等待前端启动
    if (Wait-ForService -Url "http://localhost:$FRONTEND_PORT/" -Timeout $FRONTEND_STARTUP_TIMEOUT -ServiceName "前端服务") {
        Write-ColorOutput "前端服务已启动" "Success"
    } else {
        Write-ColorOutput "前端服务启动失败" "Error"
        Write-ColorOutput "查看日志: Get-Content $FRONTEND_LOG -Tail 50" "Info"
        exit 1
    }
}

# =============================================================================
# 健康检查函数
# =============================================================================

function Test-SystemHealth {
    Write-ColorOutput "系统健康检查" "Header"
    
    $allHealthy = $true
    
    # 检查后端
    Write-ColorOutput "检查后端服务..." "Info"
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$BACKEND_PORT/api/v1/health/" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-ColorOutput "后端服务健康" "Success"
        } else {
            Write-ColorOutput "后端服务不健康" "Error"
            $allHealthy = $false
        }
    } catch {
        Write-ColorOutput "后端服务不健康" "Error"
        $allHealthy = $false
    }
    
    # 检查前端
    Write-ColorOutput "检查前端服务..." "Info"
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$FRONTEND_PORT/" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-ColorOutput "前端服务健康" "Success"
        } else {
            Write-ColorOutput "前端服务不健康" "Error"
            $allHealthy = $false
        }
    } catch {
        Write-ColorOutput "前端服务不健康" "Error"
        $allHealthy = $false
    }
    
    if ($allHealthy) {
        Write-ColorOutput "所有服务健康检查通过" "Success"
        return $true
    } else {
        Write-ColorOutput "部分服务健康检查失败" "Error"
        return $false
    }
}

# =============================================================================
# 显示系统信息
# =============================================================================

function Show-SystemInfo {
    Write-ColorOutput "系统启动完成" "Header"
    
    Write-Host "`n🎉 AutoClip 系统已成功启动！`n" -ForegroundColor White
    
    Write-Host "📊 服务状态:" -ForegroundColor Cyan
    Write-Host "  🌐 后端 API:     http://localhost:$BACKEND_PORT"
    Write-Host "  🌐 前端界面:     http://localhost:$FRONTEND_PORT"
    Write-Host "  🌐 API 文档:     http://localhost:$BACKEND_PORT/docs"
    Write-Host "  💚 健康检查:     http://localhost:$BACKEND_PORT/api/v1/health/"
    
    Write-Host "`n⚙️  内置服务:" -ForegroundColor Cyan
    Write-Host "  👷 TaskManager:  已启动（asyncio 内置）"
    Write-Host "  ⚙️  Scheduler:    已启动（定时任务）"
    Write-Host "  🗄️  ProgressStore: 已启动（内存存储）"
    
    Write-Host "`n📝 日志文件:" -ForegroundColor Cyan
    Write-Host "  后端日志: Get-Content $BACKEND_LOG -Tail 50 -Wait"
    Write-Host "  前端日志: Get-Content $FRONTEND_LOG -Tail 50 -Wait"
    
    Write-Host "`n🛑 停止系统:" -ForegroundColor Cyan
    Write-Host "  关闭 PowerShell 窗口或按 Ctrl+C"
    
    Write-Host "`n💡 使用说明:" -ForegroundColor Yellow
    Write-Host "  1. 访问 http://localhost:$FRONTEND_PORT 使用前端界面"
    Write-Host "  2. 上传视频文件或输入B站/抖音/快手链接"
    Write-Host "  3. 系统将自动启动AI处理流水线"
    Write-Host "  4. 实时查看处理进度和结果"
    
    Write-Host "`n✨ 新功能:" -ForegroundColor Green
    Write-Host "  • 快手视频下载（多解析器自动切换）"
    Write-Host "  • 抖音视频下载（Playwright + yt-dlp）"
    Write-Host "  • B站视频下载（支持番剧和视频）"
    Write-Host "  • 首页分页（20/30/50/100 条/页）"
    Write-Host ""
}

# =============================================================================
# 主函数
# =============================================================================

function Main {
    Write-ColorOutput "AutoClip 系统启动器 v2.0 (Windows)" "Header"
    
    # 检查管理员权限（可选）
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-ColorOutput "建议以管理员身份运行以避免权限问题" "Warning"
        Write-ColorOutput "如果遇到权限错误，请右键点击 PowerShell 选择'以管理员身份运行'" "Info"
        Write-ColorOutput "继续以普通用户身份运行..." "Info"
        Start-Sleep -Seconds 2
    }
    
    # 环境检查
    Test-Environment
    
    # 启动服务
    Initialize-Environment
    Initialize-Database
    Start-Backend
    Start-Frontend
    
    # 健康检查
    if (Test-SystemHealth) {
        Show-SystemInfo
        
        # 保持脚本运行
        Write-ColorOutput "系统运行中... 按 Ctrl+C 停止" "Info"
        Write-Host "`n按任意键退出..." -ForegroundColor Yellow
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    } else {
        Write-ColorOutput "系统启动失败，请检查日志" "Error"
        exit 1
    }
}

# 运行主函数
try {
    Main
} catch {
    Write-ColorOutput "发生错误: $_" "Error"
    Write-ColorOutput "错误详情: $($_.Exception.Message)" "Error"
    exit 1
}
