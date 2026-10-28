"""转写流水线 - Web 服务与 MCP 服务共享的核心逻辑。

职责：
1. 任务生命周期管理（创建 / 执行 / 查询）
2. 结果缓存（相同「链接 + 模型 + 时间戳选项」复用结果）
3. 临时文件与过期缓存清理（按命名空间隔离，避免多进程互相误删）

目录约定：
    temp/cache/                    结果缓存，所有服务共享
    temp/tasks/<namespace>/<id>/   任务工作目录，按服务隔离
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Callable

from core.audio import extract_audio
from core.downloader import download_video
from core.transcriber import transcribe_audio

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
CACHE_DIR = TEMP_DIR / "cache"
TASKS_DIR = TEMP_DIR / "tasks"

VALID_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large")

try:
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_DAYS", "7")) * 86400
except ValueError:
    CACHE_TTL_SECONDS = 7 * 86400

# 进度回调：callback(status, message)
ProgressCallback = Callable[[str, str], None] | None


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_STATUSES = frozenset(
    {TaskStatus.PENDING, TaskStatus.DOWNLOADING, TaskStatus.EXTRACTING, TaskStatus.TRANSCRIBING}
)


def validate_url(url: str) -> str:
    """校验并返回规范化后的B站链接。"""
    url = (url or "").strip()
    if not url:
        raise ValueError("视频链接不能为空")
    if "bilibili.com" not in url and "b23.tv" not in url:
        raise ValueError("请输入有效的B站视频链接（支持 bilibili.com 和 b23.tv 短链）")
    return url


def validate_model(model: str) -> str:
    """校验 Whisper 模型名。"""
    if model not in VALID_MODELS:
        raise ValueError(f"模型必须是: {', '.join(VALID_MODELS)}")
    return model


def build_cache_key(url: str, model: str, with_timestamps: bool) -> str:
    """为相同输入生成稳定的结果缓存键。"""
    payload = json.dumps(
        {"url": url, "model": model, "with_timestamps": with_timestamps},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Task:
    """一次转写任务的状态。字段名与 Web API 保持兼容。"""

    def __init__(
        self,
        task_id: str,
        url: str,
        model: str,
        with_timestamps: bool = True,
        cache_key: str = "",
        work_dir: str = "",
    ):
        self.task_id = task_id
        self.url = url
        self.model = model
        self.with_timestamps = with_timestamps
        self.cache_key = cache_key
        self.work_dir = work_dir
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.status = TaskStatus.PENDING
        self.progress_message = "等待处理..."
        self.result_text = ""
        self.error = ""
        self.cached = False

    def update(self, status: TaskStatus, message: str):
        self.status = status
        self.progress_message = message
        self.updated_at = time.time()

    def snapshot(self, include_result: bool = True) -> dict:
        """导出为可序列化的字典。"""
        data = {
            "task_id": self.task_id,
            "url": self.url,
            "model": self.model,
            "with_timestamps": self.with_timestamps,
            "status": self.status.value,
            "message": self.progress_message,
            "cached": self.cached,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished": self.status in {TaskStatus.COMPLETED, TaskStatus.FAILED},
        }
        if include_result:
            data["result"] = self.result_text
            data["length"] = len(self.result_text)
        return data


class TranscriptService:
    """转写服务：管理任务、缓存与清理。

    每个进程（Web / MCP）用一个独立命名空间，互不干扰，
    但共享同一份结果缓存，避免重复转写。
    """

    def __init__(self, namespace: str = "default", ttl_seconds: int = CACHE_TTL_SECONDS):
        self.namespace = namespace
        self.root = TASKS_DIR / namespace
        self.root.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._transcribe_lock = threading.Lock()  # Whisper 串行执行，避免多任务抢资源
        self.cleanup(startup=True)

    # ─── 任务管理 ────────────────────────────────────────
    def create_task(self, url: str, model: str = "base", with_timestamps: bool = True) -> Task:
        url = validate_url(url)
        model = validate_model(model)
        task_id = uuid.uuid4().hex[:12]
        task = Task(
            task_id=task_id,
            url=url,
            model=model,
            with_timestamps=with_timestamps,
            cache_key=build_cache_key(url, model, with_timestamps),
            work_dir=str(self.root / task_id),
        )
        with self._lock:
            self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

    def submit(self, url: str, model: str = "base", with_timestamps: bool = True) -> Task:
        """提交任务并立即返回，转写在后台线程执行。"""
        task = self.create_task(url, model, with_timestamps)

        cached = self._read_cache(task)
        if cached is not None:
            task.result_text, task.work_dir = cached
            task.cached = True
            task.update(TaskStatus.COMPLETED, "已使用缓存结果")
            return task

        thread = threading.Thread(target=self.run, args=(task,), daemon=True)
        thread.start()
        return task

    def run(self, task: Task, progress: ProgressCallback = None) -> Task:
        """阻塞执行整个转写流程（下载 → 提取音频 → 转写）。"""
        work_dir = task.work_dir
        try:
            os.makedirs(work_dir, exist_ok=True)

            self._advance(task, TaskStatus.DOWNLOADING, "正在下载视频...", progress)
            video_path = download_video(task.url, work_dir)

            self._advance(task, TaskStatus.EXTRACTING, "正在提取音频...", progress)
            audio_path = extract_audio(video_path, work_dir)

            self._advance(
                task, TaskStatus.TRANSCRIBING, f"正在转写语音（模型: {task.model}）...", progress
            )
            with self._transcribe_lock:
                text = transcribe_audio(
                    audio_path, model_name=task.model, with_timestamps=task.with_timestamps
                )

            task.result_text = text
            self._write_cache(task, text)

            cache_dir = str(CACHE_DIR / task.cache_key)
            task.work_dir = cache_dir
            task.cached = False
            shutil.rmtree(work_dir, ignore_errors=True)

            task.update(TaskStatus.COMPLETED, "转写完成！")
        except Exception as exc:  # noqa: BLE001 - 任务级兜底，错误透出给调用方
            task.error = str(exc)
            task.update(TaskStatus.FAILED, f"处理失败: {exc}")
        finally:
            self._cleanup_media(work_dir)
            self.cleanup()

        if progress is not None:
            progress(task.status.value, task.progress_message)
        return task

    def transcribe(
        self,
        url: str,
        model: str = "base",
        with_timestamps: bool = True,
        progress: ProgressCallback = None,
    ) -> Task:
        """一步到位的同步转写：命中缓存时直接返回。"""
        task = self.create_task(url, model, with_timestamps)
        cached = self._read_cache(task)
        if cached is not None:
            task.result_text, task.work_dir = cached
            task.cached = True
            task.update(TaskStatus.COMPLETED, "已使用缓存结果")
            return task
        return self.run(task, progress=progress)

    def result_path(self, task: Task) -> str:
        """结果文件路径（任务未完成或目录已清理时返回空字符串）。"""
        path = os.path.join(task.work_dir, "result.txt")
        return path if os.path.isfile(path) else ""

    @staticmethod
    def _advance(task: Task, status: TaskStatus, message: str, progress: ProgressCallback):
        task.update(status, message)
        if progress is not None:
            progress(status.value, message)

    # ─── 结果缓存 ────────────────────────────────────────
    def _read_cache(self, task: Task) -> tuple[str, str] | None:
        """读取未过期的结果缓存，返回 (文本, 缓存目录)。"""
        cache_dir = CACHE_DIR / task.cache_key
        result_path = cache_dir / "result.txt"
        if not result_path.is_file():
            return None
        if time.time() - result_path.stat().st_mtime > self.ttl:
            shutil.rmtree(cache_dir, ignore_errors=True)
            return None
        return result_path.read_text(encoding="utf-8"), str(cache_dir)

    @staticmethod
    def _write_cache(task: Task, text: str):
        """原子写入结果缓存，避免进程中断留下半个结果。"""
        cache_dir = CACHE_DIR / task.cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_path = cache_dir / "result.txt.tmp"
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, cache_dir / "result.txt")

    # ─── 清理 ────────────────────────────────────────────
    def cleanup(self, startup: bool = False):
        """清理过期任务目录、结果缓存与内存任务记录。

        startup=True 时额外强制清空本命名空间下上次运行遗留的任务目录。
        """
        now = time.time()

        if startup:
            for directory in self.root.iterdir():
                if directory.is_dir():
                    shutil.rmtree(directory, ignore_errors=True)
                else:
                    try:
                        directory.unlink()
                    except OSError:
                        pass

        # 本命名空间下的过期任务目录（跳过仍在运行的）
        active_dirs = {
            os.path.abspath(task.work_dir)
            for task in self.list_tasks()
            if task.status in ACTIVE_STATUSES
        }
        for directory in self.root.iterdir():
            if not directory.is_dir() or os.path.abspath(str(directory)) in active_dirs:
                continue
            self._remove_if_expired(directory, now)

        # 过期结果缓存
        for directory in CACHE_DIR.iterdir():
            if directory.is_dir():
                self._remove_if_expired(directory, now)

        # 过期的内存任务记录
        with self._lock:
            expired = [
                task_id
                for task_id, task in self._tasks.items()
                if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}
                and now - task.created_at > self.ttl
            ]
            for task_id in expired:
                self._tasks.pop(task_id, None)

    def _remove_if_expired(self, directory: Path, now: float):
        try:
            mtimes = [directory.stat().st_mtime]
            mtimes += [p.stat().st_mtime for p in directory.rglob("*") if p.is_file()]
            if now - max(mtimes) > self.ttl:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            pass

    @staticmethod
    def _cleanup_media(work_dir: str):
        """清理临时媒体文件，只保留 result.txt。"""
        try:
            for ext in ("*.mp4", "*.wav", "*.m4a", "*.webm"):
                for file in Path(work_dir).glob(ext):
                    file.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            pass
