"""音频提取模块 - 使用 ffmpeg 从视频中提取音频"""

import os
import subprocess


def extract_audio(video_path: str, output_dir: str) -> str:
    """
    从视频文件中提取音频为 WAV 格式（16kHz 单声道，适合 Whisper）。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录

    Returns:
        提取的音频文件路径
    """
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = os.path.join(output_dir, f"{video_name}.wav")

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",                  # 不要视频
        "-acodec", "pcm_s16le", # 16-bit PCM
        "-ar", "16000",         # 16kHz 采样率
        "-ac", "1",             # 单声道
        "-y",                   # 覆盖已有文件
        audio_path,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(f"音频提取失败: {result.stderr.strip()}")

    if not os.path.exists(audio_path):
        raise RuntimeError("音频提取完成但未找到输出文件")

    return audio_path
