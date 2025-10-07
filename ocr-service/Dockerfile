FROM dtcooper/raspberrypi-os:bookworm

ENV PIP_INDEX_URL=https://www.piwheels.org/simple
ENV PIP_EXTRA_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
# Prefer Debian site before pip site; avoid user site
ENV PYTHONPATH=/usr/lib/python3/dist-packages:/usr/local/lib/python3.11/dist-packages
ENV PYTHONNOUSERSITE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    python3-picamera2 \
    tesseract-ocr \
    python3-opencv \
    python3-reportlab \
    libcamera-dev \
    libcamera-apps \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Important: do not let pip replace numpy (use Debian's); only upgrade if needed
RUN python3 -m pip install --break-system-packages \
    pillow \
    rapidfuzz \
    pytesseract \
    fastapi "uvicorn[standard]" \
    torch torchvision \
    mediapipe ultralytics

WORKDIR /app
COPY . /app

EXPOSE 9000
CMD ["python3", "-m", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "debug"]

