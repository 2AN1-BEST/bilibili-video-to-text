# B站视频转文字

将B站视频中的语音内容自动提取并转换为文字。基于 OpenAI Whisper 本地模型，无需联网 API，隐私安全。

提供两种使用方式：

- **MCP 服务**：供 CodeBuddy / Claude Desktop 等任意 MCP 客户端的 Agent 调用（`mcp_server.py`）
- **Web 服务**：浏览器里粘贴链接转写（`app.py`，原有能力保留）

两者共用同一条转写流水线与结果缓存，可同时运行、互不干扰。

## 环境要求

- [uv](https://docs.astral.sh/uv/getting-started/installation/)（Python 版本与依赖均由 uv 管理）
- ffmpeg（需在系统 PATH 中）
- 磁盘空间：Whisper 模型约 150MB ~ 3GB（取决于所选模型）

## 快速开始

```bash
# 1. 安装依赖（会自动准备 Python 3.12 与虚拟环境）
uv sync

# 2. 启动 Web 服务，访问 http://127.0.0.1:8000
uv run python app.py
```

Windows 用户可直接双击 `start.bat`，脚本会检查环境、同步依赖并启动 Web 服务。

> 无 NVIDIA GPU 时，PyPI 上的 torch 默认捆绑约 2.5GB 的 CUDA 运行时。本项目 `pyproject.toml`
> 已把 torch 指向官方 CPU 源；若机器有 NVIDIA GPU，删掉 `[tool.uv.sources]` 整段后重新
> `uv sync` 即可装回带 CUDA 的版本。

## 作为 MCP 服务使用

### 1. 在 MCP 客户端中注册

```json
{
  "mcpServers": {
    "bilibili-video-to-text": {
      "command": "uv",
      "args": [
        "--directory",
        "D:/MyData/projects/lab/bilibili-video-to-text",
        "run",
        "mcp_server.py"
      ]
    }
  }
}
```

- `--directory` 换成本项目在你机器上的绝对路径；Windows 路径用 `/` 更省心。
- 若客户端找不到 `uv`，把 `command` 换成 uv 可执行文件的绝对路径
  （如 `C:/Users/<你>/AppData/Local/uv/uv.exe`，可用 `where uv` 查看）。
- 客户端会自动拉起服务并通过 stdio 通信，无需手动启动。

### 2. 可用工具

| 工具 | 说明 |
|------|------|
| `bilibili_get_video_info` | 获取视频标题、UP主、时长等信息（不下载、不转写），建议转写前先调用 |
| `bilibili_start_transcribe_task` | 提交转写任务并立即返回 `task_id`（**推荐**，适合中长视频） |
| `bilibili_get_task_status` | 轮询任务进度，完成后附带结果预览 |
| `bilibili_get_transcript` | 取已完成任务的转写全文 |
| `bilibili_transcribe_video` | 一步到位返回全文（阻塞等待，仅建议几分钟内的短视频） |
| `bilibili_list_models` | 列出可选 Whisper 模型及取舍 |

另有资源 `transcript://{task_id}`，可直接读取某任务的转写结果。

### 3. 典型调用流程

```text
bilibili_get_video_info(url)                       → 确认时长
bilibili_start_transcribe_task(url, model="base")   → task_id
bilibili_get_task_status(task_id)                   → 轮询直到 status=completed
bilibili_get_transcript(task_id)                    → 全文
```

转写是重活（CPU 上耗时约为视频时长的数倍），长视频务必用异步方式，避免触发调用超时。

### 4. 调试与自检

```bash
# 以 HTTP 方式启动，端点为 http://127.0.0.1:8001/mcp
uv run mcp_server.py --transport http --port 8001

# 用 MCP Inspector 连接：Transport 选 Streamable HTTP，URL 填上面的端点
npx -y @modelcontextprotocol/inspector

# 按真实客户端方式拉起 stdio 服务，验证协议通信是否正常
uv run python scripts/mcp_stdio_check.py

# 冒烟测试（默认只跑离线用例，不联网、不转写）
uv run pytest -q
```

不想装 Inspector 时，用 curl 也能确认 HTTP 服务是否活着：

```bash
curl -X POST http://127.0.0.1:8001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

返回含 `"serverInfo":{"name":"bilibili-video-to-text"...}` 的 SSE 消息即正常。

验证缓存是否生效：对同一个链接用相同模型连发两次转写请求，第二次应命中缓存并在 1 秒左右返回 `completed`。

## Web 使用方法

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

首次使用某个模型时会自动下载，之后会缓存在本地。相同的视频链接、模型和时间戳选项会复用转写结果，默认保留 7 天，Web 与 MCP 服务共享同一份缓存。

缓存位于 `temp/cache/`。服务启动时会清理自己上次运行遗留的临时任务目录，并自动清理超过 7 天的结果缓存。可通过环境变量 `CACHE_TTL_DAYS` 调整保留天数，例如 `CACHE_TTL_DAYS=30 uv run python app.py`。

## 项目结构

```text
bilibili-video-to-text/
├── app.py              # FastAPI Web 服务
├── mcp_server.py       # MCP 服务（FastMCP，stdio / http）
├── pyproject.toml      # uv 管理的依赖与项目配置
├── core/
│   ├── pipeline.py     # 转写流水线：任务管理、结果缓存、过期清理（Web / MCP 共用）
│   ├── downloader.py   # 视频下载与元数据抓取（yt-dlp）
│   ├── audio.py        # 音频提取（ffmpeg）
│   └── transcriber.py  # 语音转写（Whisper）
├── static/
│   └── index.html      # Web 前端页面
├── scripts/
│   └── mcp_stdio_check.py  # stdio 协议连通性自检
├── tests/
│   └── test_mcp_smoke.py   # MCP 服务冒烟测试
└── temp/               # 临时文件和转写结果缓存（按 TTL 自动清理）
```

## 常见问题

**Q: 下载视频失败？**
A: 部分视频可能需要登录 Cookie。可在 yt-dlp 配置中添加 Cookie，或确认视频链接可正常访问。

**Q: 转写速度很慢？**
A: 处理时间取决于视频时长和模型大小。无 GPU 时建议使用 tiny 或 base 模型。有 NVIDIA GPU 会自动加速（需装带 CUDA 的 torch）。

**Q: MCP 客户端里看不到工具？**
A: 先跑 `uv run python scripts/mcp_stdio_check.py` 确认服务本身正常；再检查配置里的
`--directory` 是否指向项目根目录、uv 能否被客户端找到。

**Q: HTTP 方式启动报 `KeyError: 'websockets-sansio'`：**
A: uvicorn 版本过低。fastmcp 的 HTTP 传输需要 uvicorn>=0.35，执行 `uv sync` 更新依赖。

**Q: 支持其他平台的视频吗？**
A: yt-dlp 支持上千个网站，但本项目只校验了B站链接。修改 `core/pipeline.py` 中的
`validate_url` 即可放开其他平台。

**Q: 想用 pip 而不是 uv 部署？**
A: 依赖以 `pyproject.toml` 为唯一真源，需要时导出：`uv export --no-emit-project -o requirements.txt`。
