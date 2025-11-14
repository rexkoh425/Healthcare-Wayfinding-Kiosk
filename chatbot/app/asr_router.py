from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Optional

import anyio
import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .settings import settings

router = APIRouter(tags=["asr"])


class AsrOut(BaseModel):
    text: str
    language: Optional[str] = None
    duration_sec: Optional[float] = None


# ----------------------------
# Remote-first configuration
# ----------------------------
# Set this in your Pi/container env to offload:
#   WHISPER_REMOTE_BASE=http://<DESKTOP-IP>:8000
_REMOTE_BASE = (getattr(settings, "WHISPER_REMOTE_BASE", None) or os.getenv("WHISPER_REMOTE_BASE") or "").rstrip("/")


async def _remote_transcribe_bytes(
    data: bytes,
    *,
    filename_suffix: str,
    language: Optional[str],
) -> AsrOut:
    if not _REMOTE_BASE:
        raise RuntimeError("WHISPER_REMOTE_BASE not set")

    url = f"{_REMOTE_BASE}/transcribe"
    files = {"audio": (f"audio{filename_suffix}", data, "application/octet-stream")}
    form = {}
    if language:
        form["language"] = language

    # generous timeouts for large audio
    timeout = httpx.Timeout(600.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, files=files, data=form)
    if r.status_code != 200:
        # bubble up remote error body to help debugging
        detail = None
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise HTTPException(status_code=502, detail=f"Remote Whisper error: {detail}")

    js = r.json()
    # Accept common field names
    return AsrOut(
        text=js.get("text") or js.get("transcript") or "",
        language=js.get("language") or js.get("transcript_language"),
        duration_sec=js.get("duration") or js.get("duration_sec"),
    )


# ----------------------------
# Local fallback (unchanged)
# ----------------------------
_model_lock = Lock()
_model = None  # type: ignore[var-annotated]


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel  # lazy import to keep Pi light
                _model = WhisperModel(
                    settings.WHISPER_MODEL_NAME,
                    device=settings.WHISPER_DEVICE,
                    compute_type=settings.WHISPER_PRECISION,
                )
    return _model


async def _local_transcribe_bytes(
    data: bytes,
    *,
    suffix: str = ".webm",
    language: Optional[str] = None,
) -> AsrOut:
    """Transcribe raw audio bytes using the local Whisper model."""
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
                language=getattr(info, "language", None),
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


# ----------------------------
# Public helpers & route
# ----------------------------
async def transcribe_audio_bytes(
    data: bytes,
    *,
    suffix: str = ".webm",
    language: Optional[str] = None,
) -> AsrOut:
    """Remote-first transcription; falls back to local if not configured."""
    if _REMOTE_BASE:
        return await _remote_transcribe_bytes(data, filename_suffix=suffix, language=language)
    return await _local_transcribe_bytes(data, suffix=suffix, language=language)


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