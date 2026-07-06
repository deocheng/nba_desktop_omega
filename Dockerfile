# ── Stage 1: Builder ──
FROM python:3.10-slim AS builder

WORKDIR /build

# Install build deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──
FROM python:3.10-slim

WORKDIR /app

# Runtime deps only (libpq for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY pyproject.toml .env.example ./

# Create cache directory
RUN mkdir -p .cache/metric_engine

# Non-root user for security
RUN useradd -m -s /bin/bash nbacore && chown -R nbacore:nbacore /app
USER nbacore

EXPOSE 5577

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5577/health || exit 1

# Production: gunicorn + uvicorn workers
CMD ["gunicorn", "backend.app:create_app", \
     "--factory", \
     "--bind", "0.0.0.0:5577", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
