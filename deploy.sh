#!/usr/bin/env bash
# The deployment step. Migrations first, then the app — in that order, in one
# script, so production cannot drift from the code again.
#
# WHY THIS EXISTS. The suite builds its schema with `create_all`, so it passes
# whether or not the real database has the tables the code queries. That is not a
# theory: `products` was missing from Supabase while every test was green, and the
# only symptom was the marketplace failing on the one machine that mattered.
# A migration is a deploy step, not a thing someone remembers.
#
# `set -euo pipefail` is load-bearing. If `alembic upgrade head` fails, this script
# exits non-zero and the app never starts, so a release fails loudly at deploy
# time instead of serving requests against a schema older than the code. That is
# the entire point: a crash here is a bad deploy, a half-migrated app is a bad
# night.
#
# Usage (host start command / container CMD):
#   ./deploy.sh
#   PORT=8080 ./deploy.sh            # binds 0.0.0.0:8080
#   PYTHON=./venv/bin/python ./deploy.sh   # explicit interpreter
#
# start.sh and scripts/dev_preview.sh are NOT this script: they run on the
# developer's machine against SQLite, with --reload and a loopback bind. Keeping
# them separate means a production run can never accidentally inherit dev flags.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python}"
PORT="${PORT:-8000}"

# Fail before touching the database rather than defaulting to something local.
# A deploy that silently used .env's development DATABASE_URL would "succeed"
# while the real database stayed untouched — the exact failure this script is
# here to prevent.
: "${DATABASE_URL:?DATABASE_URL must be set in the deploy environment}"

if [ "${APP_ENV:-}" != "" ]; then
  echo "==> APP_ENV=${APP_ENV}"
fi

echo "==> Applying migrations (alembic upgrade head)"
"$PYTHON" -m alembic upgrade head

# Print the revision actually in the database. The upgrade exiting 0 says the
# command ran; this says what the schema now is, which is what a failed deploy
# report needs to show.
echo "==> Current revision"
"$PYTHON" -m alembic current

echo "==> Starting uvicorn on 0.0.0.0:${PORT}"
# ONE worker on purpose. The websocket registry is a per-process dict, so a second
# worker means a message sent through worker A never reaches a socket held by
# worker B — it fails quietly, because sending still works and reconnect-and-fetch
# hides it. Raise this only after the registry moves to a shared store (Redis);
# docs/REMAINING-WORK.md tracks it. Concurrency is still handled per request by
# uvloop, which is the part the demo actually needs.
#
# No --reload, and 0.0.0.0 rather than 127.0.0.1: this is reached through a proxy.
exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
