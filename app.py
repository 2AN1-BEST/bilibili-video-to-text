"""B站视频语音转文字 - FastAPI 后端服务"""

import os
import uuid
import shutil
import threading
import hashlib
import json
import time
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
CACHE_DIR = TEMP_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

try:
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_DAYS", "7")) * 86400
except ValueError:
    CACHE_TTL_SECONDS = 7 * 86400

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
    def __init__(
        self,
        task_id: str,
        url: str,
        model: str,
        with_timestamps: bool = True,
        cache_key: str = "",
    ):
        self.task_id = task_id
        self.url = url
        self.model = model
        self.with_timestamps = with_timestamps
        self.cache_key = cache_key
        self.created_at = time.time()
        self.status = TaskStatus.PENDING
        self.progress_message = "等待处理..."
        self.result_text = ""
        self.error = ""
        self.work_dir = str(TEMP_DIR / task_id)


# 内存中的任务存储
tasks: dict[str, Task] = {}


def _get_cache_key(url: str, model: str, with_timestamps: bool) -> str:
    """为相同输入生成稳定的结果缓存键。"""
    payload = json.dumps(
        {"url": url, "model": model, "with_timestamps": with_timestamps},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_cache_result(cache_key: str) -> tuple[str, str] | None:
    """读取未过期的结果缓存，返回结果文本和缓存目录。"""
    cache_dir = CACHE_DIR / cache_key
    result_path = cache_dir / "result.txt"
    if not result_path.is_file():
        return None
    if time.time() - result_path.stat().st_mtime > CACHE_TTL_SECONDS:
        shutil.rmtree(cache_dir, ignore_errors=True)
        return None
    return result_path.read_text(encoding="utf-8"), str(cache_dir)


def _store_cache_result(cache_key: str, text: str):
    """原子写入结果缓存，避免进程中断留下半个结果。"""
    cache_dir = CACHE_DIR / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    temp_path = cache_dir / "result.txt.tmp"
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, cache_dir / "result.txt")


def _cleanup_expired_storage():
    """清理过期任务目录、结果缓存，并移除过期的内存任务记录。"""
    now = time.time()
    active_dirs = {
        os.path.abspath(task.work_dir)
        for task in tasks.values()
        if task.status in {
            TaskStatus.PENDING,
            TaskStatus.DOWNLOADING,
            TaskStatus.EXTRACTING,
            TaskStatus.TRANSCRIBING,
        }
    }

    for directory in TEMP_DIR.iterdir():
        if not directory.is_dir() or os.path.abspath(str(directory)) in active_dirs:
            continue
        try:
            latest_mtime = max(
                [directory.stat().st_mtime]
                + [path.stat().st_mtime for path in directory.rglob("*") if path.is_file()]
            )
            if now - latest_mtime > CACHE_TTL_SECONDS:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            continue

    expired_task_ids = [
        task_id
        for task_id, task in tasks.items()
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}
        and now - task.created_at > CACHE_TTL_SECONDS
    ]
    for task_id in expired_task_ids:
        tasks.pop(task_id, None)


def _cleanup_startup_storage():
    """服务启动时强制清理上次运行遗留的任务工作目录。"""
    for directory in TEMP_DIR.iterdir():
        if directory.is_dir() and directory != CACHE_DIR:
            shutil.rmtree(directory, ignore_errors=True)
        elif directory.is_file():
            try:
                directory.unlink()
            except OSError:
                pass


_cleanup_startup_storage()
_cleanup_expired_storage()


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
    task_work_dir = task.work_dir
    try:
        os.makedirs(task_work_dir, exist_ok=True)

        # 1. 下载视频
        task.status = TaskStatus.DOWNLOADING
        task.progress_message = "正在下载视频..."
        video_path = download_video(task.url, task_work_dir)

        # 2. 提取音频
        task.status = TaskStatus.EXTRACTING
        task.progress_message = "正在提取音频..."
        audio_path = extract_audio(video_path, task_work_dir)

        # 3. 语音转写
        task.status = TaskStatus.TRANSCRIBING
        task.progress_message = f"正在转写语音（模型: {task.model}）..."
        text = transcribe_audio(audio_path, model_name=task.model, with_timestamps=task.with_timestamps)

        # 4. 保存结果
        task.result_text = text
        result_path = os.path.join(task_work_dir, "result.txt")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(text)

        _store_cache_result(task.cache_key, text)
        task.work_dir = str(CACHE_DIR / task.cache_key)
        shutil.rmtree(task_work_dir, ignore_errors=True)

        task.status = TaskStatus.COMPLETED
        task.progress_message = "转写完成！"

    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.progress_message = f"处理失败: {e}"

    finally:
        # 清理视频和音频大文件，保留结果
        _cleanup_media(task_work_dir)
        _cleanup_expired_storage()


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

    cache_key = _get_cache_key(url, req.model, req.with_timestamps)
    task_id = uuid.uuid4().hex[:12]
    cached_result = _get_cache_result(cache_key)
    task = Task(
        task_id=task_id,
        url=url,
        model=req.model,
        with_timestamps=req.with_timestamps,
        cache_key=cache_key,
    )
    tasks[task_id] = task

    if cached_result:
        task.result_text, task.work_dir = cached_result
        task.status = TaskStatus.COMPLETED
        task.progress_message = "已使用缓存结果"
        return TaskResponse(task_id=task_id, status=task.status, message=task.progress_message)

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
