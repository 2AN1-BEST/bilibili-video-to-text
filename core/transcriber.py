"""语音转写模块 - 使用 OpenAI Whisper 进行语音识别"""

import whisper


_model_cache = {}


def get_model(model_name: str = "base"):
    """加载并缓存 Whisper 模型，避免重复加载。"""
    if model_name not in _model_cache:
        _model_cache[model_name] = whisper.load_model(model_name)
    return _model_cache[model_name]


def transcribe_audio(audio_path: str, model_name: str = "base", language: str = "zh") -> str:
    """
    使用 Whisper 将音频转写为文本。

    Args:
        audio_path: 音频文件路径（WAV 格式）
        model_name: Whisper 模型大小 (tiny/base/small/medium/large)
        language: 语言代码，默认中文 "zh"

    Returns:
        转写的纯文本内容
    """
    model = get_model(model_name)

    result = model.transcribe(
        audio_path,
        language=language,
        verbose=False,
    )

    return result["text"].strip()
