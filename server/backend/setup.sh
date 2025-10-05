#!/bin/bash

apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libdbus-1-dev \
    libcups2-dev \
    meson \
    ninja-build \
 && rm -rf /var/lib/apt/lists/*

