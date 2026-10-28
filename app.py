"""B站视频语音转文字 - FastAPI 后端服务

与 MCP 服务（mcp_server.py）共用 core/pipeline.py 的转写流水线，
两者共享同一份结果缓存，但任务目录按命名空间隔离，可同时运行。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from core.pipeline import TaskStatus, TranscriptService

BASE_DIR = Path(__file__).parent

app = FastAPI(title="B站视频转文字", version="1.0.0")
service = TranscriptService(namespace="web")


# ─── 请求/响应模型 ──────────────────────────────────────
class TranscribeRequest(BaseModel):
    url: str
    model: str = "base"  # tiny / base / small / medium / large
    with_timestamps: bool = True  # 是否分段并附带时间戳


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    result: str = ""
    error: str = ""


def _to_response(task) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        message=task.progress_message,
        result=task.result_text if task.status == TaskStatus.COMPLETED else "",
        error=task.error if task.status == TaskStatus.FAILED else "",
    )


# ─── API 路由 ───────────────────────────────────────────
@app.post("/api/transcribe", response_model=TaskResponse)
def create_transcribe_task(req: TranscribeRequest):
    """提交一个视频转写任务。"""
    try:
        task = service.submit(req.url, req.model, req.with_timestamps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_response(task)


@app.get("/api/task/{task_id}", response_model=TaskResponse)
def get_task_status(task_id: str):
    """查询任务状态。"""
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return _to_response(task)


@app.get("/api/download/{task_id}")
def download_result(task_id: str):
    """下载转写结果文本文件。"""
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    result_path = service.result_path(task)
    if not result_path:
        raise HTTPException(status_code=404, detail="结果文件不存在")

    return FileResponse(
        result_path,
        media_type="text/plain; charset=utf-8",
        filename=f"transcript_{task_id}.txt",
    )


# ─── 前端页面 ───────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_index():
    """返回前端页面。"""
    index_path = BASE_DIR / "static" / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


# ─── 启动入口 ───────────────────────────────────────────
def main():
    import uvicorn

    print("=" * 50)
    print("  B站视频转文字服务已启动")
    print("  访问 http://127.0.0.1:8000 使用")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
