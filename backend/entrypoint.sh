#!/usr/bin/env bash
# Applies migrations, then hands off to the CMD (uvicorn by default).
# This is what makes a bare `docker compose up` produce a migrated database.
set -euo pipefail

echo "[entrypoint] applying database migrations..."
alembic upgrade head
echo "[entrypoint] migrations up to date."

exec "$@"
