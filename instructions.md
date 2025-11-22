# Instructions

This file covers setup, environment variables, local/dev commands, Docker, certificates, vector store rebuild, and device notes. For a high-level project overview, see `README.md`.

## Prerequisites
- Node.js 18+
- Python 3.10+ (for server/chatbot)
- Docker + Docker Compose (optional)
- (GPU option) NVIDIA driver + container toolkit

## Repo Setup
```bash
git clone https://github.com/CDE3301-IS303/cde3301-wayfinding-kiosk.git
cd cde3301-wayfinding-kiosk
```

## Env setup by component

### touchscreen-display (`.env.local`)
- `NEXT_PUBLIC_CHATBOT_API_BASE` (e.g., http://localhost:8001)
- `NEXT_PUBLIC_OCR_API_BASE` (e.g., http://localhost:9000)
- `NEXT_PUBLIC_BACKEND_API_BASE` (e.g., http://localhost:8080)
- `NEXT_PUBLIC_WS_URL` (e.g., ws://localhost:8080)

### server (`.env` in `server/` if needed)
- `BACKEND_RELOAD=1` (enable FastAPI autoreload during dev)
- Ports: WS 8080, FastAPI 8000

### chatbot (`chatbot/.env`)
- LLM/RAG: `GEMINI_API_KEY`, `GEMINI_MODEL`, `CHROMA_DIR`, `CHROMA_COLLECTION`, `CHROMA_EMBED_MODEL`, `CHROMA_TOP_K`
- ASR: `WHISPER_MODE=local|remote`, `WHISPER_DEVICE=cpu|cuda`, `WHISPER_MODEL_NAME`, `WHISPER_PRECISION`, `WHISPER_LANGUAGE`, `WHISPER_REMOTE_BASE` (if offloading)
- TTS: `PIPER_VOICE`, `PIPER_VOICE_PATH`, `PIPER_BIN`, `PIPER_LENGTH_SCALE`
- CORS: `CORS_ORIGINS=["http://localhost:3000"]`

### OCR (`ocr-service/.env` if used)
- Camera settings: `USB_DEVICE_INDEX`, `USB_WIDTH`, `USB_HEIGHT`, `USB_FPS`
- YOLO paths: `YOLO_CONFIG_DIR`, `YOLO_DEBUG_DIR`, `YOLO_DEBUG_LIMIT`

### Data & Vector Store
- Data JSONL: `data/alexandra_hospital_chroma_merged.jsonl`
- Chroma store: `.chroma/ah` (mounted read/write in compose)

## Run locally (without Docker)

### Touchscreen UI
```bash
cd touchscreen-display
npm install
npm run dev   # http://localhost:3000
```

### Server (WS + FastAPI bridge)
```bash
cd server
npm install
python -m pip install -r backend/requirements.txt
BACKEND_RELOAD=1 npm start   # WS:8080, FastAPI:8000
```

### Chatbot (Gemini + Chroma RAG)
```bash
cd chatbot
python -m pip install -r requirements.txt
uvicorn app.dialog:app --host 0.0.0.0 --port 8001
```

### Hologram display
```bash
npx http-server hologram-display -p 3001
```

### Vector store rebuild
```bash
python utils/scripts/prepare_chroma_data.py \
  --input data/alexandra_hospital_chroma_merged.jsonl \
  --output data/alexandra_hospital_chroma_merged.jsonl \
  --ascii-fallback \
  --chroma-dir .chroma/ah \
  --collection alexandra_hospital \
  --embedding-model sentence-transformers/all-MiniLM-L6-v2
```

## Run with Docker Compose
```bash
docker compose up --build       # foreground
docker compose up -d            # detached
```
Key ports (via Caddy defaults): frontend 3000, chatbot 8001, WS 8080, OCR 9000.

## Certificates (self-signed for localhost)
```bash
docker run --rm -v "${PWD}/certs:/certs" alpine sh -c \
  "apk add --no-cache openssl && \
   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
   -keyout /certs/key.pem -out /certs/cert.pem -subj '/CN=localhost'"
```

## Devices
- Hologram assets: `hologram-display/assets` (`wave.mp4`, `listen.mp4`, `reply.mp4`)
- RFID/NFC: see `rfid/` and `nfc/` for setup and Dockerfiles
- OCR: requires camera devices (`/dev/video*`) when running on hardware

## Tips
- Refresh Chroma after changing JSONL data.
- For GPU ASR, ensure NVIDIA runtime and CUDA-compatible drivers.
- Keep secrets out of git; use local `.env` files.
