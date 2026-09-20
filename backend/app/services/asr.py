"""语音识别服务（FunASR，中文高准确率）。

模型：paraformer-zh（语音识别）+ fsmn-vad（端点检测）+ ct-punc（标点恢复）
懒加载：首次调用时下载并加载模型（约 500MB），后续复用。
"""
import logging
import os
import tempfile

logger = logging.getLogger("ailearn.asr")

_model = None
_model_loading = False


def get_model():
    """懒加载 FunASR 模型（首次调用耗时，后续复用）。"""
    global _model, _model_loading
    if _model is not None:
        return _model
    if _model_loading:
        raise RuntimeError("ASR 模型正在加载中，请稍后重试")
    _model_loading = True
    try:
        from funasr import AutoModel

        logger.info("Loading FunASR: paraformer-zh + fsmn-vad + ct-punc ...")
        _model = AutoModel(
            model="paraformer-zh",
            model_revision="v2.0.4",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
        )
        logger.info("FunASR model loaded successfully.")
        return _model
    except Exception:
        _model_loading = False
        raise


def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """识别音频字节，返回带标点的文本。

    支持 wav/mp3/m4a/webm 等（FunASR 内部用 ffmpeg/soundfile 解码）。
    要求：单声道优先，采样率不低于 16kHz。
    """
    if not audio_bytes:
        return ""
    model = get_model()
    ext = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        res = model.generate(input=tmp_path)
        if res and len(res) > 0:
            text = res[0].get("text", "")
            return text.strip()
        return ""
    except Exception as e:
        logger.error("ASR transcribe failed: %s", e)
        raise RuntimeError(f"语音识别失败: {e}") from e
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def is_available() -> bool:
    """检查 FunASR 是否已安装。"""
    try:
        import funasr  # noqa: F401

        return True
    except ImportError:
        return False
