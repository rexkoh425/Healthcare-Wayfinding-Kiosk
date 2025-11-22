# Chatbot (Gemini + Chroma RAG + ASR/TTS)

## Overview
The chatbot serves multimodal queries for Alexandra Hospital using:
- Retrieval Augmented Generation (Chroma vector store, AH data)
- Gemini LLM for intent and response
- Whisper (local or remote) for STT
- Piper for TTS

## Key Files
- `chatbot/app/dialog.py` – FastAPI app, prompt logic, ASR/TTS routing, Chroma retrieval
- `chatbot/app/settings.py` – env config (LLM, ASR, RAG, TTS, CORS)
- `chatbot/requirements.txt` – dependencies

## Environment Variables (`chatbot/.env`)
LLM/RAG:
- `LLM_PROVIDER=gemini`
- `GEMINI_API_KEY=<your_key>`
- `GEMINI_MODEL=gemini-2.5-flash`
- `CHROMA_DIR=/app/.chroma/ah`
- `CHROMA_COLLECTION=alexandra_hospital`
- `CHROMA_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2`
- `CHROMA_TOP_K=4` (or desired top-k)

ASR (Whisper):
- `WHISPER_MODE=local|remote|auto`
- `WHISPER_DEVICE=cpu|cuda`
- `WHISPER_MODEL_NAME=base|small|medium`
- `WHISPER_PRECISION=int8|float16|float32`
- `WHISPER_LANGUAGE=en`
- `WHISPER_REMOTE_BASE=http://<gpu-host>:8000` (if offloading)

TTS (Piper):
- `PIPER_VOICE=en_US-amy-medium`
- `PIPER_VOICE_PATH=/voices/en_US-amy-medium.onnx`
- `PIPER_BIN=/usr/local/bin/piper`
- `PIPER_LENGTH_SCALE=1.0`

CORS:
- `CORS_ORIGINS=["http://localhost:3000"]`

## Running Locally
```bash
cd chatbot
python -m pip install -r requirements.txt
uvicorn app.dialog:app --host 0.0.0.0 --port 8001
```

## Vector Store (Chroma)
- Persisted at `.chroma/ah`, collection `alexandra_hospital`.
- Rebuild/upsert:
```bash
python utils/scripts/prepare_chroma_data.py \
  --input data/alexandra_hospital_chroma_merged.jsonl \
  --output data/alexandra_hospital_chroma_merged.jsonl \
  --ascii-fallback \
  --chroma-dir .chroma/ah \
  --collection alexandra_hospital \
  --embedding-model sentence-transformers/all-MiniLM-L6-v2
```

## Prompt Behavior
- General FAQs: respond directly, `intent="general"`, no destination confirmation.
- Route queries: `intent="route"`, up to 3 canonical destinations from `data/directions-ah.csv`, confirm destination in TTS.
- Context: top-k Chroma snippets injected into the prompt; no hallucinations allowed.

## Notes
- GPU ASR: use `WHISPER_DEVICE=cuda` and ensure CUDA/cuDNN in the container; otherwise stick to CPU.
- Keep `.env` out of git. Update Chroma whenever JSONL data changes.
