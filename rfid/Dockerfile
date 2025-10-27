# Use official Python 3.11 slim image for ARM (compatible with Raspberry Pi)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-serial \
        && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install rpi-lgpio

# Copy app code
COPY . .

# Expose Flask portd
EXPOSE 5000

# Run the Python script
CMD ["python", "rfid-serial.py"]
