"""视频下载模块 - 使用 yt-dlp 下载B站视频"""

import os
import sys
import subprocess
from pathlib import Path


def _get_env():
    """构造包含 Python Scripts 目录的环境变量，确保 yt-dlp 可被找到。"""
    env = os.environ.copy()
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    user_scripts = os.path.expanduser(
        r"~\AppData\Roaming\Python\Python312\Scripts"
    )
    extra = os.pathsep.join([scripts_dir, user_scripts])
    env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


def download_video(url: str, output_dir: str, progress_callback=None) -> str:
    """
    下载B站视频到指定目录。

    Args:
        url: B站视频链接
        output_dir: 输出目录
        progress_callback: 进度回调函数 callback(percent: float, message: str)

    Returns:
        下载的视频文件路径
    """
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-overwrites",
        "--print", "after_move:filepath",
        # 绕过B站 412 反爬
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "--referer", "https://www.bilibili.com",
        "--extractor-args", "bilibili:api=app",
        url,
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_get_env(),
    )

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"视频下载失败: {stderr.strip()}")

    filepath = stdout.strip().split("\n")[-1]
    if not filepath or not os.path.exists(filepath):
        # 尝试从目录中找到最新下载的文件
        files = list(Path(output_dir).glob("*.mp4"))
        if files:
            filepath = str(max(files, key=os.path.getmtime))
        else:
            raise RuntimeError("下载完成但未找到视频文件")

    return filepath
