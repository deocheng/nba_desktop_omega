#!/usr/bin/env bash
# NBACore Studio v8 — Development Start Script
# Usage: ./start.sh [dev|prod]

set -e

MODE=${1:-dev}

if [ "$MODE" = "prod" ]; then
    echo "Starting NBACore Studio v8 (production)..."
    exec gunicorn backend.app:create_app \
        --factory \
        --bind "0.0.0.0:${SERVER_PORT:-5577}" \
        --workers "${WORKERS:-4}" \
        --worker-class uvicorn.workers.UvicornWorker \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
else
    echo "Starting NBACore Studio v8 (development)..."
    exec uvicorn backend.app:create_app \
        --factory \
        --reload \
        --host "${SERVER_HOST:-127.0.0.1}" \
        --port "${SERVER_PORT:-5577}"
fi
