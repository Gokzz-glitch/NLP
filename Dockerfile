# SmartSalai Edge-Sentinel — Development & CI Container
# Usage:
#   docker build -t smartsalai-dev .
#   docker run --rm smartsalai-dev pytest tests/ -v
#
# SAFETY NOTE: This container is for development and testing ONLY.
# Do NOT deploy in any production vehicle system.
# See SAFETY.md for full safety disclaimer.

FROM python:3.11-slim

LABEL maintainer="SmartSalai Edge-Sentinel Team"
LABEL description="SmartSalai Edge-Sentinel — Research prototype. NOT for vehicle deployment."
LABEL version="0.1.0"

WORKDIR /app

# Install system dependencies required by pdfplumber / pyttsx3 / sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-dev \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-lock.txt

# Copy source code
COPY . .

# Run tests by default
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
