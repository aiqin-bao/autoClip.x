@echo off
REM AutoClip.x Windows 启动脚本 (批处理文件)
REM 版本: 2.0
REM 功能: 启动完整的AutoClip系统（后端API + 前端界面）

echo.
echo ========================================
echo   AutoClip 系统启动器 v2.0 (Windows)
echo ========================================
echo.

REM 检查 PowerShell 是否可用
where powershell >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未找到 PowerShell
    echo 请确保 Windows PowerShell 已安装
    pause
    exit /b 1
)

REM 检查 PowerShell 脚本是否存在
if not exist "start_autoclip.ps1" (
    echo [错误] 未找到 start_autoclip.ps1
    echo 请确保该文件在当前目录中
    pause
    exit /b 1
)

echo [信息] 正在启动 PowerShell 脚本...
echo [信息] 如果遇到执行策略错误，请以管理员身份运行以下命令：
echo         Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
echo.

REM 运行 PowerShell 脚本
powershell -ExecutionPolicy Bypass -File "start_autoclip.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] PowerShell 脚本执行失败
    echo.
    echo 常见解决方案：
    echo 1. 以管理员身份运行此脚本
    echo 2. 运行以下命令允许脚本执行：
    echo    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    echo 3. 直接运行 PowerShell 脚本：
    echo    powershell -ExecutionPolicy Bypass -File start_autoclip.ps1
    echo.
    pause
    exit /b 1
)

pause
