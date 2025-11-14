from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from google import genai
from pydantic import BaseModel, ValidationError

from .asr_router import AsrOut, transcribe_audio_bytes
from .settings import settings


from .tts_router import router as tts_router, synthesize_wav
import csv


logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


app = FastAPI(title="Kiosk Dialog (Gemini + Intent)")
allow = settings.CORS_ORIGINS or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(tts_router)

# ---------- Models ----------
class Msg(BaseModel):
    role: str
    content: str


class LlmOut(BaseModel):
    intent: str
    locations: List[str] = []
    response_text: str
    ask_clarification: bool = False
    repeat_request: bool = False


class TalkOut(BaseModel):
    llm: LlmOut


class TalkVoiceOut(BaseModel):
    transcript: str
    transcript_language: Optional[str] = None
    llm: LlmOut
    audio_wav_b64: Optional[str] = None

def load_destinations_from_csv(csv_file):
    """
    Load destinations from CSV file and format as Python list string.
    CSV should have destinations in one column or comma-separated.
    """
    destinations = []
    
    with open(csv_file, 'r') as file:
        reader = csv.reader(file)
        next(reader)  # Skip header row
        for row in reader:
            if row:  # Skip empty rows
                dest = row[0].strip()  # Get first column only
                if dest:
                    destinations.append(dest)
    
    sorted_destinations = destinations
    
    # Format as Python list string
    python_string = "\n".join([f"- {dest}" for dest in destinations])
    
    return python_string

def _format_locations_for_prompt(locations: List[str]) -> str:
    cleaned = [loc.strip() for loc in locations if isinstance(loc, str) and loc.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} or {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", or {cleaned[-1]}"


def _build_tts_response_text(llm_out: LlmOut) -> str:
    if llm_out.locations:
        location_phrase = _format_locations_for_prompt(llm_out.locations)
        if location_phrase:
            return f"Can I confirm you want to go to {location_phrase}?"
    base = (llm_out.response_text or "").strip()
    return base or "Okay."


# Accepted ASR language codes (mirrors faster-whisper)
_ASR_LANG_CODES = {"en", "ms", "ta", "zh"}


def _normalise_asr_language(lang: Optional[str]) -> Optional[str]:
    """Return a language code accepted by faster-whisper or None for auto-detect."""

    if not lang:
        return None
    stripped = lang.strip()
    if not stripped:
        return None
    lowered = stripped.lower().replace("_", "-")
    if lowered in _ASR_LANG_CODES:
        return lowered
    # Accept locale-style strings like en-us by taking primary subtag
    primary = lowered.split("-", 1)[0]
    if primary in _ASR_LANG_CODES:
        return primary
    logger.warning("Unsupported ASR language '%s'; falling back to auto", lang)
    return None


# ---------- Gemini client ----------

def _get_gemini_client() -> "genai.Client":
    if settings.LLM_PROVIDER != "gemini":
        raise HTTPException(500, detail="Unsupported LLM_PROVIDER")
    if not settings.GEMINI_API_KEY:
        raise HTTPException(500, detail="GEMINI_API_KEY missing")
    return genai.Client(api_key=settings.GEMINI_API_KEY)

def _gemini_model():
    return _get_gemini_client()


# ---------- Prompt ----------
# SYSTEM_INSTRUCTIONS = """You are a hospital kiosk assistant. Classify the user's input into one of exactly four intents:
# 1) "route" for route directions requests
# 2) "general" for general enquiries (opening hours, where is pharmacy?, etc.)
# 3) "repeat" if they ask to repeat instructions
# 4) "nonsense" if the input is not meaningful for this context

# When intent="route", determine the top THREE most likely destinations the user wants next (highest confidence first), using conversation history to resolve context and ignoring filler or noisy words. Every candidate must be mapped to the following canonical names only:
# """

# SYSTEM_INSTRUCTIONS += load_destinations_from_csv("/data/directions-ah.csv")

# SYSTEM_INSTRUCTIONS += """

# If the user refers to a clinic letter in any form (e.g. "clinic e", "klinick ee"), normalise it to the correct "Clinic <Letter>" entry. Remove duplicates and return the top three distinct destinations (or fewer if you are unsure). If you truly cannot decide, set ask_clarification=true and craft a clarifying response.

# Return STRICT JSON only:
# {
#   "intent": "route|general|repeat|nonsense",
#   "locations": ["..."],  // ordered list of up to three canonical destinations for the user's next move
#   "response_text": "string",
#   "ask_clarification": true|false,
#   "repeat_request": true|false
# }"""

SYSTEM_INSTRUCTIONS = """You are a school campus kiosk assistant. Classify the user's input into one of exactly four intents:
1) "route" for route directions requests
2) "general" for general enquiries (opening hours, where is library?, etc.)
3) "repeat" if they ask to repeat instructions
4) "nonsense" if the input is not meaningful for this context

When intent="route", determine the top THREE most likely destinations the user wants next (highest confidence first), using conversation history to resolve context and ignoring filler or noisy words. Every candidate must be mapped to the following canonical names only:
"""

# SYSTEM_INSTRUCTIONS += load_destinations_from_csv("/data/directions-nus.csv")
SYSTEM_INSTRUCTIONS += load_destinations_from_csv("/data/directions-showcase.csv")

SYSTEM_INSTRUCTIONS += """

Remove duplicates. If you truly cannot decide, set ask_clarification=true and craft a clarifying response.
Return STRICT JSON only:
{
  "intent": "route|general|repeat|nonsense",
  "locations": ["..."],  // ordered list of up to three canonical destinations for the user's next move
  "response_text": "string",
  "ask_clarification": true|false,
  "repeat_request": true|false
}"""

def _format_history(history: Optional[List[Msg]]) -> str:
    if not history:
        return ""
    parts = []
    for msg in history:
        role = msg.role.upper()
        parts.append(f"{role}: {msg.content}")
    return "\n".join(parts)


def _build_user_message(user_text: str, history: Optional[List[Msg]]) -> str:
    context = _format_history(history)
    if context:
        return f"PREVIOUS:\n{context}\n\nUSER_INPUT:\n{user_text}\n\nReturn STRICT JSON only. No markdown."
    return f"USER_INPUT:\n{user_text}\n\nReturn STRICT JSON only. No markdown."


def _coerce_json(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _invoke_llm(user_text: str, history: Optional[List[Msg]]) -> TalkOut:
    client = _get_gemini_client()
    prompt = SYSTEM_INSTRUCTIONS + "\n\n" + _build_user_message(user_text, history)

    logger.info("Invoking Gemini; prompt preview=%s", prompt[:200].replace("\n", "\\n"))

    try:
        resp = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
    except Exception:
        logger.exception("Gemini API call failed")
        raise
    raw_text = getattr(resp, "text", None)
    if not raw_text and hasattr(resp, "output_text"):
        raw_text = getattr(resp, "output_text")
    text = str(raw_text or "").strip()
    if not text:
        text = str(resp).strip()
    if not text:
        logger.error("Gemini responded without text")
        raise HTTPException(502, detail="Empty response from Gemini")

    try:
        data = _coerce_json(text)
    except Exception:
        logger.warning("Gemini response not JSON, attempting repair; raw=%s", text[:400])
        repair = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=f"Fix to VALID JSON only (no commentary):\n{text}",
        )
        repair_text_raw = getattr(repair, "text", None) or getattr(repair, "output_text", None)
        repair_text = str(repair_text_raw or "{}")
        data = _coerce_json(repair_text)

    intent = data.get("intent", "nonsense")
    locations = data.get("locations") if isinstance(data.get("locations"), list) else []
    logger.info(
        "Gemini intent parsed; intent=%s locations=%s clarify=%s repeat=%s",
        intent,
        locations,
        bool(data.get("ask_clarification", False)),
        bool(data.get("repeat_request", False)),
    )
    return TalkOut(
        llm=LlmOut(
            intent=intent,
            locations=[str(x).strip() for x in locations if str(x).strip()],
            response_text=str(data.get("response_text", "")).strip() or "Okay.",
            ask_clarification=bool(data.get("ask_clarification", False)),
            repeat_request=bool(data.get("repeat_request", False)),
        )
    )


def _parse_history_form(raw: Optional[str]) -> Optional[List[Msg]]:
    if raw in (None, ""):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="history must be valid JSON list") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="history must be a JSON list")
    history: List[Msg] = []
    for item in value:
        try:
            history.append(Msg(**item))
        except (TypeError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="Invalid history entry") from exc
    return history


@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html>
      <body style="font-family: system-ui, sans-serif; padding: 20px;">
        <h2 style="margin:0 0 6px 0;">Talk Backend</h2>
        <p style="opacity:.85;">
          Session: <code>demo-session</code>
        </p>
      </body>
    </html>
    """


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/health")
def health():
    return {"status": "ok", "provider": settings.LLM_PROVIDER, "model": settings.GEMINI_MODEL}


@app.post("/talk-voice")
async def talk_voice(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    text: Optional[str] = Form(default=None),
    history: Optional[str] = Form(default=None),
    return_mode: str = Form("audio"),
    language: Optional[str] = Form(default="en"),
):
    history_items = _parse_history_form(history)

    language_code = _normalise_asr_language(language)

    logger.info(
        "talk_voice request received session_id=%s file=%s return_mode=%s history_present=%s",
        session_id,
        audio.filename,
        return_mode,
        bool(history),
    )

    try:
        audio_bytes = await audio.read()
        if not audio_bytes and not text:
            logger.warning("talk_voice missing audio and text")
            raise HTTPException(status_code=400, detail="Audio or text input required")

        suffix = Path(audio.filename or "audio").suffix or ".webm"
        transcript: AsrOut | None = None
        user_text = (text or "").strip()

        if audio_bytes:
            logger.debug("Running ASR bytes=%s suffix=%s", len(audio_bytes), suffix)
            transcript = await transcribe_audio_bytes(audio_bytes, suffix=suffix, language=language_code)
            user_text = transcript.text or user_text
            logger.info(
                "ASR complete transcript=%s language=%s duration=%s",
                (transcript.text or "")[:200],
                transcript.language,
                transcript.duration_sec,
            )

        user_text = (user_text or "").strip()

        if not user_text:
            logger.warning("No transcript text available; returning fallback")
            fallback = TalkOut(
                llm=LlmOut(
                    intent="nonsense",
                    locations=[],
                    response_text="I didn't catch that. Please try again.",
                    ask_clarification=True,
                    repeat_request=True,
                )
            )
            response_text = fallback.llm.response_text
            wav_bytes = await synthesize_wav(response_text)

            if (return_mode or "").lower() == "json":
                payload = TalkVoiceOut(
                    transcript="",
                    transcript_language=transcript.language if transcript else None,
                    llm=fallback.llm,
                    audio_wav_b64=base64.b64encode(wav_bytes).decode("ascii"),
                )
                return JSONResponse(payload.model_dump())

            headers = {
                "X-Transcript": "",
                "X-Intent": fallback.llm.intent,
                "X-Transcript-Language": transcript.language if transcript and transcript.language else "",
            }
            headers = {k: v for k, v in headers.items() if v}
            return StreamingResponse(io.BytesIO(wav_bytes), media_type="audio/wav", headers=headers)

        logger.info("Calling LLM with transcript=%s", user_text[:200])
        talk_out = _invoke_llm(user_text, history_items)
        response_text = _build_tts_response_text(talk_out.llm)
        if response_text != talk_out.llm.response_text:
            try:
                talk_out.llm.response_text = response_text
            except (TypeError, ValueError, AttributeError):
                if hasattr(talk_out.llm, "model_dump"):
                    llm_payload = talk_out.llm.model_dump()
                else:
                    llm_payload = talk_out.llm.dict()
                llm_payload["response_text"] = response_text
                talk_out = TalkOut(llm=LlmOut(**llm_payload))
        logger.info(
            "Generating TTS intent=%s response_preview=%s return_mode=%s",
            talk_out.llm.intent,
            response_text[:200],
            return_mode,
        )
        wav_bytes = await synthesize_wav(response_text)

        if (return_mode or "").lower() == "json":
            payload = TalkVoiceOut(
                transcript=user_text,
                transcript_language=transcript.language if transcript else None,
                llm=talk_out.llm,
                audio_wav_b64=base64.b64encode(wav_bytes).decode("ascii"),
            )
            return JSONResponse(payload.model_dump())

        headers = {
            "X-Transcript": user_text,
            "X-Intent": talk_out.llm.intent,
        }
        if transcript and transcript.language:
            headers["X-Transcript-Language"] = transcript.language

        return StreamingResponse(io.BytesIO(wav_bytes), media_type="audio/wav", headers=headers)
    except HTTPException as exc:
        logger.warning(
            "talk_voice returning HTTPException status=%s detail=%s",
            exc.status_code,
            getattr(exc, "detail", None),
        )
        raise
    except Exception:
        logger.exception("talk_voice pipeline failed")
        raise