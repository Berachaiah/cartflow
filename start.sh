#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
source venv/bin/activate

PORT="${PORT:-8000}"
if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
  echo "Port $PORT is busy, stopping the old process..."
  lsof -ti tcp:"$PORT" | xargs kill -9
fi

python -m alembic upgrade head
exec python -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT"
