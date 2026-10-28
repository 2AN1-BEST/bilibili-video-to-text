"""MCP 服务冒烟测试。

默认只跑离线用例（工具暴露、参数校验、状态查询）。
需要真实网络/模型端到端转写的用例，设置环境变量才会执行：

    MCP_E2E_URL=https://www.bilibili.com/video/BVxxx uv run pytest -m e2e -s
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastmcp import Client

from mcp_server import mcp

EXPECTED_TOOLS = {
    "bilibili_get_video_info",
    "bilibili_transcribe_video",
    "bilibili_start_transcribe_task",
    "bilibili_get_task_status",
    "bilibili_get_transcript",
    "bilibili_list_models",
}

BILI_URL = os.getenv("MCP_E2E_URL", "https://www.bilibili.com/video/BV1GJ411x7h7")


@pytest.mark.asyncio
async def test_expected_tools_are_exposed():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert EXPECTED_TOOLS <= {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_list_models_mentions_every_model():
    async with Client(mcp) as client:
        result = await client.call_tool("bilibili_list_models", {})
    text = result.data if isinstance(result.data, str) else str(result.data)
    for model in ("tiny", "base", "small", "medium", "large"):
        assert model in text


@pytest.mark.asyncio
async def test_non_bilibili_url_is_rejected():
    async with Client(mcp) as client:
        with pytest.raises(Exception):
            await client.call_tool("bilibili_get_video_info", {"url": "https://example.com/video/1"})


@pytest.mark.asyncio
async def test_invalid_model_is_rejected():
    async with Client(mcp) as client:
        with pytest.raises(Exception):
            await client.call_tool(
                "bilibili_start_transcribe_task", {"url": BILI_URL, "model": "huge"}
            )


@pytest.mark.asyncio
async def test_unknown_task_id_is_rejected():
    async with Client(mcp) as client:
        with pytest.raises(Exception):
            await client.call_tool("bilibili_get_task_status", {"task_id": "not-exist"})


@pytest.mark.asyncio
async def test_transcript_resource_reports_missing_task():
    async with Client(mcp) as client:
        result = await client.read_resource("transcript://not-exist")
    text = "".join(str(getattr(c, "text", "")) for c in result)
    assert "不存在" in text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_async_transcribe_flow():
    """端到端：提交异步任务 → 轮询状态 → 取全文。"""
    if not os.getenv("MCP_E2E_URL"):
        pytest.skip("未设置 MCP_E2E_URL，跳过真实转写")

    model = os.getenv("MCP_E2E_MODEL", "tiny")
    async with Client(mcp) as client:
        started = await client.call_tool(
            "bilibili_start_transcribe_task", {"url": BILI_URL, "model": model}
        )
        task_id = started.data["task_id"]
        assert task_id

        for _ in range(120):  # 最多等 20 分钟
            status = await client.call_tool("bilibili_get_task_status", {"task_id": task_id})
            if status.data["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(10)

        assert status.data["status"] == "completed", status.data.get("error")

        transcript = await client.call_tool("bilibili_get_transcript", {"task_id": task_id})
        assert isinstance(transcript.data, str) and transcript.data.strip()
