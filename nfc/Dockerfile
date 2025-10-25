FROM python:3.11-slim-bookworm

# Install required build tools and libraries
RUN apt-get update && apt-get install -y \
    python3-dev \
    gcc \
    g++ \
    libgpiod-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .

# Install your Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    # Install drop-in replacement for RPi.GPIO
    && pip install rpi-lgpio pyserial

# Copy the rest of your project
COPY . .

# Set up environment (optional but safe)
ENV GPIOZERO_PIN_FACTORY=lgpio

# Default command
CMD ["python", "nfc.py"]
