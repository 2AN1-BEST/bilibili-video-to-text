@echo off
chcp 65001 >nul
echo ========================================
echo   B站视频转文字 - 环境检查与启动
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 ffmpeg，请先安装并添加到 PATH
    echo 下载地址: https://ffmpeg.org/download.html
    echo 或使用 winget: winget install ffmpeg
    pause
    exit /b 1
)

:: 安装依赖
echo [1/2] 安装 Python 依赖...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

:: 启动服务
echo [2/2] 启动服务...
echo.
python app.py
pause
