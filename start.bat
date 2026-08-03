@echo off
setlocal
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1

echo ========================================
echo   Bilibili Video to Text - Environment Check and Startup
echo ========================================
echo.

:: Check Python
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    ) else (
        echo [ERROR] Python was not found. Please install Python 3.9+.
        echo Download: https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

:: Check ffmpeg
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ffmpeg was not found. Please install it and add it to PATH.
    echo Download: https://ffmpeg.org/download.html
    echo Or use: winget install ffmpeg
    pause
    exit /b 1
)

:: Install dependencies
echo [1/2] Installing Python dependencies...
%PYTHON_CMD% -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

:: Start service
echo [2/2] Starting service...
echo.
%PYTHON_CMD% app.py
if errorlevel 1 (
    echo [ERROR] The application exited unexpectedly.
    pause
    exit /b 1
)
pause
