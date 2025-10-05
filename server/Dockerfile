FROM node:20-bookworm

WORKDIR /app

# Install Python runtime and shared system dependencies for both services
RUN apt-get update   && apt-get install -y --no-install-recommends     python3     python3-pip     python3-venv     python3-dev     build-essential     tesseract-ocr     libdbus-1-dev     libcups2-dev     meson     ninja-build     libgl1     libglib2.0-0   && rm -rf /var/lib/apt/lists/*

# Isolate Python packages in a dedicated virtual environment to avoid
# conflicts with the base Debian-managed Python installation
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Node dependencies first to leverage Docker layer caching
COPY package*.json ./
RUN npm install --omit=dev   && mkdir -p /opt/node_modules   && cp -R node_modules/. /opt/node_modules
ENV NODE_PATH=/opt/node_modules

# Install Python dependencies using cached requirements layer
COPY backend/requirements.txt backend/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel   && python -m pip install --no-cache-dir -r backend/requirements.txt

# Copy application sources
COPY . .

EXPOSE 8080 8000

CMD ["npm", "run", "start"]
