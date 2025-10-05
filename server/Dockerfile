FROM node:20-bookworm

WORKDIR /app

# Install Python runtime and shared system dependencies for both services
RUN apt-get update   && apt-get install -y --no-install-recommends     python3     python3-pip     python3-venv     python3-dev     build-essential     tesseract-ocr     libdbus-1-dev     libcups2-dev     meson     ninja-build     libgl1     libglib2.0-0   && rm -rf /var/lib/apt/lists/*

# Install Node dependencies first to leverage Docker layer caching
COPY package*.json ./
RUN npm install --omit=dev

# Install Python dependencies using cached requirements layer
COPY backend/requirements.txt backend/requirements.txt
RUN python3 -m pip install --upgrade pip setuptools wheel   && python3 -m pip install --no-cache-dir -r backend/requirements.txt

# Copy application sources
COPY . .

EXPOSE 8080 8000

CMD ["npm", "run", "start"]
