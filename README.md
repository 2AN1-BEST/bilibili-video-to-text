# B站视频转文字

将B站视频中的语音内容自动提取并转换为文字。基于 OpenAI Whisper 本地模型，无需联网 API，隐私安全。

## 环境要求

- Python 3.9+
- ffmpeg（需在系统 PATH 中）
- 磁盘空间：Whisper 模型约 150MB ~ 3GB（取决于所选模型）

## 快速开始

### Windows

双击 `start.bat`，脚本会自动检查环境、安装依赖并启动服务。

### 手动启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python app.py
```

启动后访问 http://127.0.0.1:8000 即可使用。

## 使用方法

1. 在浏览器打开 http://127.0.0.1:8000
2. 粘贴B站视频链接（支持 bilibili.com 和 b23.tv 短链）
3. 选择识别模型（推荐 base 或 small）
4. 点击「开始转写」，等待处理完成
5. 在线查看结果，或复制 / 下载 TXT 文件

## 模型选择

| 模型 | 大小 | 速度 | 精度 | 适用场景 |
|------|------|------|------|----------|
| tiny | ~75MB | 最快 | 一般 | 快速预览 |
| base | ~150MB | 较快 | 良好 | 日常使用（推荐） |
| small | ~500MB | 中等 | 较高 | 对精度有要求 |
| medium | ~1.5GB | 较慢 | 高 | 专业场景 |
| large | ~3GB | 最慢 | 最高 | 最高精度需求 |

首次使用某个模型时会自动下载，之后会缓存在本地。相同的视频链接、模型和时间戳选项会复用转写结果，默认保留 7 天。

缓存位于 `temp/cache/`。服务启动时会强制清理上次运行遗留的临时任务目录，并自动清理超过 7 天的结果缓存。可通过环境变量 `CACHE_TTL_DAYS` 调整保留天数，例如 `CACHE_TTL_DAYS=30 python app.py`。

## 项目结构

```
bilibili-video-to-text/
├── app.py              # FastAPI 主服务
├── requirements.txt    # Python 依赖
├── start.bat           # Windows 一键启动
├── core/
│   ├── downloader.py   # 视频下载（yt-dlp）
│   ├── audio.py        # 音频提取（ffmpeg）
│   └── transcriber.py  # 语音转写（Whisper）
├── static/
│   └── index.html      # Web 前端页面
└── temp/               # 临时文件和转写结果缓存（按 TTL 自动清理）
```

## 常见问题

**Q: 下载视频失败？**
A: 部分视频可能需要登录 Cookie。可在 yt-dlp 配置中添加 Cookie，或确认视频链接可正常访问。

**Q: 转写速度很慢？**
A: 处理时间取决于视频时长和模型大小。无 GPU 时建议使用 tiny 或 base 模型。有 NVIDIA GPU 会自动加速。

**Q: 支持其他平台的视频吗？**
A: yt-dlp 支持上千个网站，但本项目前端仅校验了B站链接。修改 app.py 中的校验逻辑即可支持其他平台。
