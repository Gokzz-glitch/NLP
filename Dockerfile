# SmartSalai Edge-Sentinel — Development / CI Container
#
# IMPORTANT: This image is for RESEARCH and SIMULATION only.
# It is NOT intended for deployment in safety-critical vehicle systems.
# See SAFETY.md for mandatory disclaimers.
#
# Build:
#   docker build -t smartsalai-dev .
#
# Run tests:
#   docker run --rm smartsalai-dev python -m pytest tests/ -q
#
# Run simulation:
#   docker run --rm smartsalai-dev python sim/run_video_sim.py --synthetic --duration 30

FROM python:3.11-slim

LABEL maintainer="Gokzz-glitch/NLP" \
      description="SmartSalai Edge-Sentinel — research prototype (NOT ADAS)" \
      safety="SIMULATION ONLY — NOT CERTIFIED FOR VEHICLE OPERATION"

# System deps for pdfplumber / Tesseract OCR fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency spec first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir hypothesis httpx

# Copy source
COPY . .

# Safety disclaimer printed on every container start
ENV SMARTSALAI_DISCLAIMER="SIMULATION ONLY — NOT CERTIFIED ADAS — DO NOT USE TO MAKE REAL DRIVING DECISIONS"
RUN echo '#!/bin/sh\necho "⚠  $SMARTSALAI_DISCLAIMER"\nexec "$@"' \
    > /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "pytest", "tests/", "-q", "--tb=short"]
