from __future__ import annotations

import base64
import io
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .settings import settings


logger = logging.getLogger("uvicorn.error")


router = APIRouter(tags=["tts"])


class TtsIn(BaseModel):
    text: str
    return_mode: str = "audio"  # "audio" | "json"


class TtsOut(BaseModel):
    audio_wav_b64: str


_voice_path = Path(settings.PIPER_VOICE_PATH)
_config_path = Path(f"{settings.PIPER_VOICE_PATH}.json")
_piper_bin = Path(settings.PIPER_BIN or "/usr/local/bin/piper")


def _ensure_files() -> None:
    if not _piper_bin.exists():
        raise HTTPException(status_code=500, detail=f"Piper binary not found at {_piper_bin}")
    if not _voice_path.exists():
        raise HTTPException(status_code=500, detail=f"Piper voice not found at {_voice_path}")
    if not _config_path.exists():
        # Config is required for proper synthesis
        raise HTTPException(status_code=500, detail=f"Piper voice config not found at {_config_path}")


async def synthesize_wav(text: str) -> bytes:
    """Generate speech audio using the Piper CLI."""

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required for TTS")

    _ensure_files()

    logger.info("Piper synthesis requested; text_preview=%s", text[:200])

    def _run() -> bytes:
        payload = (json.dumps({"text": text}) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_out:
            tmp_out_path = tmp_out.name

        try:
            cmd = [
                str(_piper_bin),
                "--model",
                str(_voice_path),
                "--config",
                str(_config_path),
                "--output_file",
                tmp_out_path,
            ]
            proc = subprocess.run(
                cmd,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", "ignore")
                logger.error("Piper synthesis failed rc=%s stderr=%s", proc.returncode, stderr)
                raise HTTPException(
                    status_code=500,
                    detail=f"Piper synthesis failed: {stderr}",
                )
            with open(tmp_out_path, "rb") as fh:
                data = fh.read()
                logger.info("Piper synthesis complete; bytes=%s", len(data))
                return data
        finally:
            try:
                os.remove(tmp_out_path)
            except OSError:
                pass

    return await anyio.to_thread.run_sync(_run)


@router.post("/speak")
async def speak(body: TtsIn):
    wav_bytes = await synthesize_wav(body.text)

    if body.return_mode.lower() == "json":
        payload = TtsOut(audio_wav_b64=base64.b64encode(wav_bytes).decode("ascii"))
        return payload

    return StreamingResponse(io.BytesIO(wav_bytes), media_type="audio/wav")


__all__ = ["router", "synthesize_wav", "TtsOut"]
