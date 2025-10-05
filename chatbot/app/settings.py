from __future__ import annotations

import json
from typing import List, Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _safe_json_loads(value: Union[str, bytes, bytearray]):
    """Attempt JSON decode but fall back to the original value on failure."""
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


class Settings(BaseSettings):
    # Read .env at project root; ignore unexpected env vars
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", json_loads=_safe_json_loads)

    # ---------------- CORS ----------------
    CORS_ORIGINS: List[str] = Field(default_factory=list)

    # ---------------- ASR (Whisper) ----------------
    # New canonical names (preferred)
    WHISPER_MODEL_NAME: str = "base"       # e.g., "base", "small", "medium"
    WHISPER_DEVICE: str = "cpu"            # "cpu" | "cuda" | "auto"
    WHISPER_PRECISION: str = "int8"        # "int8" | "float16" | "float32"
    WHISPER_LANGUAGE: Optional[str] = None

    # Back-compat env names (will be mapped to the canonical ones if provided)
    WHISPER_MODEL: Optional[str] = None    # legacy alias for WHISPER_MODEL_NAME
    WHISPER_COMPUTE: Optional[str] = None  # legacy alias for WHISPER_PRECISION

    # ---------------- LLM ----------------
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"  # modern default; works with google-genai

    # ---------------- TTS (Piper) ----------------
    PIPER_VOICE: str = "en_US-amy-medium"
    PIPER_VOICE_PATH: str = "/voices/en_US-amy-medium.onnx"
    PIPER_BIN: str = "/usr/local/bin/piper"

    # ---------- Validators & Normalizers ----------

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _coerce_cors(cls, v):
        """
        Accepts:
          - JSON string: '["http://a","http://b"]'
          - CSV string:  'http://a,http://b'
          - List[str]
        Returns a clean list[str].
        """
        if v in (None, "", []):
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Try JSON first…
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                # …fallback: CSV
                return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("WHISPER_MODEL_NAME", mode="before")
    @classmethod
    def _fallback_model_name(cls, v, info):
        """
        If WHISPER_MODEL_NAME isn't set but legacy WHISPER_MODEL is,
        map it across.
        """
        if v not in (None, ""):
            return v
        data = info.data if hasattr(info, "data") else {}
        legacy = data.get("WHISPER_MODEL")
        return legacy or "base"

    @field_validator("WHISPER_PRECISION", mode="before")
    @classmethod
    def _fallback_precision(cls, v, info):
        """
        If WHISPER_PRECISION isn't set but legacy WHISPER_COMPUTE is,
        map it across.
        """
        if v not in (None, ""):
            return v
        data = info.data if hasattr(info, "data") else {}
        legacy = data.get("WHISPER_COMPUTE")
        return legacy or "int8"

    @field_validator("GEMINI_MODEL", mode="before")
    @classmethod
    def _trim_gemini_model(cls, v):
        """
        Trim whitespace; allow either bare family (e.g. gemini-2.5-flash)
        or versioned suffix (e.g. gemini-2.5-flash-001).
        """
        if isinstance(v, str):
            return v.strip()
        return v


settings = Settings()
