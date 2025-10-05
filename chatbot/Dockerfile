FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg curl ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Correct Piper TTS binary (arm64 on Pi, else x86_64)
RUN set -eux; \
    arch="$(uname -m)"; \
    if [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then \
        BIN_URL="https://github.com/rhasspy/piper/releases/latest/download/piper_arm64"; \
    else \
        BIN_URL="https://github.com/rhasspy/piper/releases/latest/download/piper"; \
    fi; \
    curl -L "$BIN_URL" -o /usr/local/bin/piper; \
    chmod +x /usr/local/bin/piper; \
    /usr/local/bin/piper --version || true

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt


COPY . /app

# ---- ENV: align with your code’s variable names ----
# Your code expects WHISPER_MODEL_NAME / WHISPER_DEVICE / WHISPER_PRECISION
# and uses PIPER_BIN + PIPER_VOICE_PATH.
ENV CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000" \
    WHISPER_MODEL_NAME=small \
    WHISPER_DEVICE=cpu \
    WHISPER_PRECISION=int8 \
    PIPER_BIN=/usr/local/bin/piper \
    PIPER_VOICE_PATH=/voices/en_US-amy-medium.onnx \
    LLM_PROVIDER=gemini \
    GEMINI_MODEL=gemini-1.5-flash-001

EXPOSE 8001
CMD ["uvicorn", "app.dialog:app", "--host", "0.0.0.0", "--port", "8001"]