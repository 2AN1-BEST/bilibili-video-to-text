"""B站视频语音转文字 - FastAPI 后端服务"""

import os
import uuid
import shutil
import threading
from enum import Enum
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from core.downloader import download_video
from core.audio import extract_audio
from core.transcriber import transcribe_audio

# ─── 配置 ───────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

app = FastAPI(title="B站视频转文字", version="1.0.0")


# ─── 数据模型 ───────────────────────────────────────────
class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    def __init__(self, task_id: str, url: str, model: str, with_timestamps: bool = True):
        self.task_id = task_id
        self.url = url
        self.model = model
        self.with_timestamps = with_timestamps
        self.status = TaskStatus.PENDING
        self.progress_message = "等待处理..."
        self.result_text = ""
        self.error = ""
        self.work_dir = str(TEMP_DIR / task_id)


# 内存中的任务存储
tasks: dict[str, Task] = {}


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


# ─── 后台处理流程 ───────────────────────────────────────
def process_task(task: Task):
    """在后台线程中执行完整的转写流程。"""
    try:
        os.makedirs(task.work_dir, exist_ok=True)

        # 1. 下载视频
        task.status = TaskStatus.DOWNLOADING
        task.progress_message = "正在下载视频..."
        video_path = download_video(task.url, task.work_dir)

        # 2. 提取音频
        task.status = TaskStatus.EXTRACTING
        task.progress_message = "正在提取音频..."
        audio_path = extract_audio(video_path, task.work_dir)

        # 3. 语音转写
        task.status = TaskStatus.TRANSCRIBING
        task.progress_message = f"正在转写语音（模型: {task.model}）..."
        text = transcribe_audio(audio_path, model_name=task.model, with_timestamps=task.with_timestamps)

        # 4. 保存结果
        task.result_text = text
        result_path = os.path.join(task.work_dir, "result.txt")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(text)

        task.status = TaskStatus.COMPLETED
        task.progress_message = "转写完成！"

    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.progress_message = f"处理失败: {e}"

    finally:
        # 清理视频和音频大文件，保留结果
        _cleanup_media(task.work_dir)


def _cleanup_media(work_dir: str):
    """清理临时媒体文件，只保留 result.txt。"""
    try:
        for ext in ("*.mp4", "*.wav", "*.m4a", "*.webm"):
            for f in Path(work_dir).glob(ext):
                f.unlink(missing_ok=True)
    except Exception:
        pass


# ─── API 路由 ───────────────────────────────────────────
@app.post("/api/transcribe", response_model=TaskResponse)
def create_transcribe_task(req: TranscribeRequest):
    """提交一个视频转写任务。"""
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="视频链接不能为空")

    # 简单校验是否为B站链接
    if "bilibili.com" not in url and "b23.tv" not in url:
        raise HTTPException(status_code=400, detail="请输入有效的B站视频链接")

    valid_models = ("tiny", "base", "small", "medium", "large")
    if req.model not in valid_models:
        raise HTTPException(status_code=400, detail=f"模型必须是: {', '.join(valid_models)}")

    task_id = uuid.uuid4().hex[:12]
    task = Task(task_id=task_id, url=url, model=req.model, with_timestamps=req.with_timestamps)
    tasks[task_id] = task

    # 启动后台线程处理
    thread = threading.Thread(target=process_task, args=(task,), daemon=True)
    thread.start()

    return TaskResponse(task_id=task_id, status=task.status, message=task.progress_message)


@app.get("/api/task/{task_id}", response_model=TaskResponse)
def get_task_status(task_id: str):
    """查询任务状态。"""
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        message=task.progress_message,
        result=task.result_text if task.status == TaskStatus.COMPLETED else "",
        error=task.error if task.status == TaskStatus.FAILED else "",
    )


@app.get("/api/download/{task_id}")
def download_result(task_id: str):
    """下载转写结果文本文件。"""
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    result_path = os.path.join(task.work_dir, "result.txt")
    if not os.path.exists(result_path):
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
if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  B站视频转文字服务已启动")
    print("  访问 http://127.0.0.1:8000 使用")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
