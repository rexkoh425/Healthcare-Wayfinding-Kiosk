FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (python, ffmpeg, curl, certs)
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ffmpeg curl ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Ensure python/pip commands exist
RUN ln -sf /usr/bin/python3 /usr/bin/python && ln -sf /usr/bin/pip3 /usr/bin/pip

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

EXPOSE 8001
CMD ["uvicorn", "app.dialog:app", "--host", "0.0.0.0", "--port", "8001"]
