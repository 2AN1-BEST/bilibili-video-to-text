@echo off
setlocal
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1

echo ========================================
echo   B站视频转文字 - 环境检查与启动
echo ========================================
echo.

:: Check ffmpeg
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未检测到 ffmpeg，请先安装并加入 PATH。
    echo 下载: https://ffmpeg.org/download.html
    echo 或执行: winget install ffmpeg
    pause
    exit /b 1
)

:: Check uv (Python 版本与依赖均由 uv 管理)
where uv >nul 2>&1
if errorlevel 1 (
    echo [i] 未检测到 uv，正在安装...
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo [ERROR] uv 安装失败，请手动安装: https://docs.astral.sh/uv/getting-started/installation/
        pause
        exit /b 1
    )
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

:: Sync dependencies
echo [1/2] 同步依赖（首次会下载 Python 与 torch，请耐心等待）...
uv sync
if errorlevel 1 (
    echo [ERROR] 依赖同步失败。
    pause
    exit /b 1
)

:: Start web service
echo [2/2] 启动 Web 服务...
echo.
uv run python app.py
if errorlevel 1 (
    echo [ERROR] 服务异常退出。
    pause
    exit /b 1
)
pause
