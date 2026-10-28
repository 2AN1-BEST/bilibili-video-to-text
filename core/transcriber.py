"""语音转写模块 - 使用 OpenAI Whisper 进行语音识别"""

# Whisper / OpenCC 都改为懒加载：torch 导入较慢，避免拖慢 MCP 服务启动
_whisper = None
_t2s = None
_model_cache = {}


def _load_whisper():
    global _whisper
    if _whisper is None:
        import whisper

        _whisper = whisper
    return _whisper


def _get_converter():
    global _t2s
    if _t2s is None:
        from opencc import OpenCC

        _t2s = OpenCC("t2s")
    return _t2s


def get_model(model_name: str = "base"):
    """加载并缓存 Whisper 模型，避免重复加载。"""
    if model_name not in _model_cache:
        _model_cache[model_name] = _load_whisper().load_model(model_name)
    return _model_cache[model_name]


def _format_timestamp(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS。"""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcribe_audio(
    audio_path: str,
    model_name: str = "base",
    language: str = "zh",
    with_timestamps: bool = True,
) -> str:
    """
    使用 Whisper 将音频转写为文本，并统一输出简体中文。

    Args:
        audio_path: 音频文件路径（WAV 格式）
        model_name: Whisper 模型大小 (tiny/base/small/medium/large)
        language: 语言代码，默认中文 "zh"
        with_timestamps: 是否按分段结果换行并附带时间戳

    Returns:
        转写的简体中文文本（按段落分行）
    """
    model = get_model(model_name)

    result = model.transcribe(
        audio_path,
        language=language,
        verbose=False,
    )

    # 按分段结果逐段输出，避免所有文字挤成一段
    paragraphs = []
    for seg in result.get("segments", []):
        seg_text = seg.get("text", "").strip()
        if not seg_text:
            continue
        # 繁体转简体
        if language == "zh":
            seg_text = _get_converter().convert(seg_text)
        if with_timestamps:
            paragraphs.append(f"[{_format_timestamp(seg.get('start', 0))}] {seg_text}")
        else:
            paragraphs.append(seg_text)

    if paragraphs:
        return "\n".join(paragraphs)

    # 兜底：无分段信息时直接使用整体文本
    text = result["text"].strip()
    if language == "zh":
        text = _get_converter().convert(text)
    return text
