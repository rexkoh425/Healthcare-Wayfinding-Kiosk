# Use official Python 3.11 slim image for ARM (Raspberry Pi compatible)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .

# Install system dependencies for evdev and USB
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-dev \
        libudev-dev \
        build-essential \
        usbutils \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir flask flask-cors evdev pyusb

# Copy application code
COPY . .

# Expose Flask port
EXPOSE 5000

# Run the Python script
CMD ["python", "rfidv1.py"]
