"""语音识别 API：上传音频 → 返回文本。"""
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..services.asr import is_available, transcribe

logger = logging.getLogger("ailearn.asr_api")
router = APIRouter(prefix="/api/v1/asr", tags=["asr"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25MB
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".aac"}


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """上传音频文件，返回识别文本。首次调用会加载模型（约 10-30 秒）。"""
    if not is_available():
        raise HTTPException(status_code=503, detail="ASR 服务未安装（funasr），请在后端虚拟环境执行 pip install funasr")

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="音频文件为空")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"音频过大（上限 {MAX_AUDIO_BYTES // 1024 // 1024}MB）")

    ext = ""
    if file.filename:
        import os

        ext = os.path.splitext(file.filename)[1].lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的音频格式: {ext}")

    try:
        text = transcribe(audio, file.filename or "audio.wav")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"text": text, "filename": file.filename}


@router.get("/status")
def asr_status():
    """检查 ASR 服务状态。"""
    from ..services.asr import _model

    return {
        "available": is_available(),
        "model_loaded": _model is not None,
        "max_size_mb": MAX_AUDIO_BYTES // 1024 // 1024,
    }
