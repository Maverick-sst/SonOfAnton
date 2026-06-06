# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy resume + linkedin data for ingestion at startup
COPY resume_x1.pdf ./resume_x1.pdf
COPY linkedIn_data/ ./linkedIn_data/

# Chroma persist dir (the file is ephemeral, so we re-ingest on startup)
RUN mkdir -p /app/data/chroma
ENV CHROMA_PERSIST_PATH=/app/data/chroma

EXPOSE 8000

# Render injects $PORT; default to 8000 locally
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
