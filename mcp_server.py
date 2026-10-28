"""B站视频转文字 · MCP 服务

基于 FastMCP 把本地 Whisper 转写能力暴露给任意 MCP 客户端（CodeBuddy、Claude Desktop 等）。

启动方式：
    uv run mcp_server.py                          # stdio（默认，供 MCP 客户端拉起）
    uv run mcp_server.py --transport http --port 8001   # HTTP，便于调试

MCP 客户端配置示例见 README「作为 MCP 服务使用」一节。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import warnings

# fastmcp 依赖链里有 DeprecationWarning 噪音，统一在导入前关掉
warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastmcp import FastMCP  # noqa: E402

from core.downloader import fetch_video_info  # noqa: E402
from core.pipeline import (  # noqa: E402
    VALID_MODELS,
    TaskStatus,
    TranscriptService,
    validate_url,
)

PREVIEW_CHARS = 300

MODEL_GUIDE: dict[str, str] = {
    "tiny": "最快 / 精度一般，约 75MB，适合快速预览",
    "base": "较快 / 精度良好，约 150MB，日常使用推荐",
    "small": "中等速度 / 精度较高，约 500MB",
    "medium": "较慢 / 精度高，约 1.5GB，专业场景",
    "large": "最慢 / 精度最高，约 3GB，最高精度需求",
}

mcp = FastMCP(
    name="bilibili-video-to-text",
    instructions=(
        "把B站视频中的语音转成简体中文文字，本地 Whisper 推理，不依赖联网 API。"
        "推荐流程：先 bilibili_get_video_info 查看标题与时长（时长越长转写越慢）；"
        "再 bilibili_start_transcribe_task 提交异步任务；"
        "然后 bilibili_get_task_status 轮询进度；完成后用 bilibili_get_transcript 取全文。"
        "几分钟内的短视频可直接用 bilibili_transcribe_video 一步拿到结果。"
        "相同链接+模型+时间戳选项会命中缓存，重复请求会立刻返回。"
    ),
    mask_error_details=False,  # 把真实错误透出给调用方，便于排查
)

service = TranscriptService(namespace="mcp")


def _require_task(task_id: str):
    task = service.get_task(task_id)
    if task is None:
        raise ValueError(f"任务不存在: {task_id}（任务记录保留 {service.ttl // 86400} 天，可能已过期）")
    return task


@mcp.tool
async def bilibili_get_video_info(url: str) -> dict:
    """获取B站视频的元数据（标题、UP主、时长、播放量等），不下载视频、不转写。

    转写前先调用它确认时长：CPU 环境下转写耗时大约是视频时长的数倍，
    过长的视频建议改用更大模型之外的策略（如先确认是否值得转写）。

    Args:
        url: B站视频链接，支持 bilibili.com 和 b23.tv 短链

    Returns:
        视频信息字典，含 title / uploader / duration / duration_string / webpage_url 等
    """
    url = validate_url(url)
    return await asyncio.to_thread(fetch_video_info, url)


@mcp.tool
async def bilibili_transcribe_video(
    url: str,
    model: str = "base",
    with_timestamps: bool = True,
) -> dict:
    """转写B站视频语音为简体中文文本，阻塞等待并一次性返回完整结果。

    这是耗时操作：下载 + 转写通常要几分钟甚至更久。仅建议用于几分钟内的短视频，
    长视频请改用 bilibili_start_transcribe_task 异步方式，避免触发调用超时。

    Args:
        url: B站视频链接，支持 bilibili.com 和 b23.tv 短链
        model: Whisper 模型，可选 tiny / base / small / medium / large，默认 base
        with_timestamps: 是否给每段文字加上 [HH:MM:SS] 时间戳，默认 True

    Returns:
        含 transcript（转写全文）、characters（字数）、cached（是否命中缓存）等字段的字典
    """
    validate_url(url)
    task = await asyncio.to_thread(service.transcribe, url, model, with_timestamps)
    if task.status == TaskStatus.FAILED:
        raise RuntimeError(f"转写失败（task_id={task.task_id}）: {task.error}")
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "cached": task.cached,
        "url": task.url,
        "model": task.model,
        "with_timestamps": task.with_timestamps,
        "characters": len(task.result_text),
        "transcript": task.result_text,
    }


@mcp.tool
async def bilibili_start_transcribe_task(
    url: str,
    model: str = "base",
    with_timestamps: bool = True,
) -> dict:
    """提交一个B站视频转写任务并立即返回，不阻塞等待。

    适合中长视频。拿到 task_id 后用 bilibili_get_task_status 轮询，
    状态变为 completed 后再调 bilibili_get_transcript 取全文。

    Args:
        url: B站视频链接，支持 bilibili.com 和 b23.tv 短链
        model: Whisper 模型，可选 tiny / base / small / medium / large，默认 base
        with_timestamps: 是否给每段文字加上 [HH:MM:SS] 时间戳，默认 True

    Returns:
        任务信息字典，含 task_id 与当前 status；命中缓存时 status 直接为 completed
    """
    validate_url(url)
    task = service.submit(url, model, with_timestamps)  # 只创建任务并起后台线程，耗时可忽略
    data = task.snapshot(include_result=False)
    data["hint"] = (
        "用 bilibili_get_task_status 轮询进度，完成后用 bilibili_get_transcript 取全文"
    )
    return data


@mcp.tool
async def bilibili_get_task_status(task_id: str, preview_chars: int = PREVIEW_CHARS) -> dict:
    """查询转写任务的状态与进度。

    status 取值：pending / downloading / extracting / transcribing / completed / failed。

    Args:
        task_id: bilibili_start_transcribe_task 返回的任务 ID
        preview_chars: 完成后附带的结果预览字数，默认 300；传 0 则不返回预览

    Returns:
        任务状态字典；completed 时会带上 characters 与 preview
    """
    task = _require_task(task_id)
    data = task.snapshot(include_result=False)
    if task.status == TaskStatus.COMPLETED:
        data["characters"] = len(task.result_text)
        if preview_chars > 0:
            data["preview"] = task.result_text[:preview_chars]
    return data


@mcp.tool
async def bilibili_get_transcript(task_id: str) -> str:
    """获取已完成任务的完整转写文本。

    必须先确认任务状态为 completed，否则会报错。

    Args:
        task_id: bilibili_start_transcribe_task 返回的任务 ID

    Returns:
        转写全文，每行一段；带时间戳时形如 [00:01:23] 文本内容
    """
    task = _require_task(task_id)
    if task.status != TaskStatus.COMPLETED:
        raise RuntimeError(
            f"任务尚未完成，当前状态: {task.status.value}（{task.progress_message}）"
        )
    return task.result_text


@mcp.tool
def bilibili_list_models() -> str:
    """列出可用的 Whisper 模型及其速度与精度取舍。

    Returns:
        Markdown 文本，说明每个模型的体积、速度、精度与适用场景
    """
    lines = [
        "| 模型 | 说明 |",
        "|------|------|",
    ]
    lines += [f"| {name} | {MODEL_GUIDE[name]} |" for name in VALID_MODELS]
    lines.append("")
    lines.append("首次使用某模型会自动下载并缓存；默认 base。")
    return "\n".join(lines)


@mcp.resource("transcript://{task_id}")
def transcript_resource(task_id: str) -> str:
    """按任务 ID 读取转写结果全文（资源形式，便于直接挂到上下文）。"""
    task = service.get_task(task_id)
    if task is None:
        return f"任务不存在: {task_id}"
    if task.status != TaskStatus.COMPLETED:
        return f"任务尚未完成，当前状态: {task.status.value} - {task.progress_message}"
    return task.result_text


def run():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="B站视频转文字 MCP 服务")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "http", "streamable-http", "sse"],
        help="传输方式，默认 stdio（MCP 客户端拉起时使用）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 传输监听地址")
    parser.add_argument("--port", type=int, default=8001, help="HTTP 传输监听端口")
    args = parser.parse_args()

    if args.transport == "stdio":
        # Windows 中文环境下 sys.stdout 默认用 GBK，含中文的 JSON-RPC 响应会乱码。
        # 注意：不能做 `sys.stdout = sys.stderr` 重定向——MCP 正是通过 sys.stdout
        # 这个对象收发消息的，改指向会把响应写进 stderr，客户端永远收不到。
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass

        # stdio 传输不接受 host / port 参数
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    run()
