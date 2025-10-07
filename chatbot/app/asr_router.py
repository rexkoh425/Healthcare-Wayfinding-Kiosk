from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Optional

import anyio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel
from pydantic import BaseModel

from .settings import settings


router = APIRouter(tags=["asr"])


class AsrOut(BaseModel):
    text: str
    language: Optional[str] = None
    duration_sec: Optional[float] = None


_model_lock = Lock()
_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = WhisperModel(
                    settings.WHISPER_MODEL_NAME,
                    device=settings.WHISPER_DEVICE,
                    compute_type=settings.WHISPER_PRECISION,
                )
    return _model


async def transcribe_audio_bytes(
    data: bytes,
    *,
    suffix: str = ".webm",
    language: Optional[str] = None,
) -> AsrOut:
    """Transcribe raw audio bytes using the configured Whisper model."""

    language = language or settings.WHISPER_LANGUAGE

    def _run() -> AsrOut:
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            model = _get_model()
            segments, info = model.transcribe(
                tmp_path,
                language=language,
                task="transcribe",
                vad_filter=True,
                beam_size=1,
            )
            text = "".join(seg.text for seg in segments).strip()
            return AsrOut(
                text=text,
                language=info.language,
                duration_sec=getattr(info, "duration", None),
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=f"ASR failed: {exc}") from exc
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return await anyio.to_thread.run_sync(_run)


@router.post("/transcribe", response_model=AsrOut)
async def transcribe(
    audio: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
) -> AsrOut:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    suffix = Path(audio.filename or "audio").suffix or ".webm"
    return await transcribe_audio_bytes(data, suffix=suffix, language=language)


__all__ = ["router", "AsrOut", "transcribe_audio_bytes"]
