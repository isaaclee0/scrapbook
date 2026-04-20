#!/bin/sh
# Container entrypoint.
#
# 1. Wait for the database to accept TCP connections (compose declares this via
#    a healthcheck for local dev, but production deployments may not, so we
#    still poll defensively).
# 2. Run migrate.py — it's idempotent, every step uses IF NOT EXISTS / column
#    probing, so re-running on every start is cheap and ensures schema upgrades
#    apply automatically when a new image rolls out.
# 3. exec the real CMD so signals (SIGTERM from docker stop) reach Python.

set -eu

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"
MAX_WAIT="${DB_WAIT_SECONDS:-60}"

echo "[entrypoint] waiting up to ${MAX_WAIT}s for ${DB_HOST}:${DB_PORT}..."
i=0
while [ "$i" -lt "$MAX_WAIT" ]; do
    if python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('${DB_HOST}', ${DB_PORT})); s.close()" 2>/dev/null; then
        echo "[entrypoint] database is reachable"
        break
    fi
    i=$((i + 1))
    sleep 1
done

if [ "$i" -ge "$MAX_WAIT" ]; then
    echo "[entrypoint] ERROR: database ${DB_HOST}:${DB_PORT} not reachable after ${MAX_WAIT}s" >&2
    exit 1
fi

echo "[entrypoint] running migrate.py..."
if ! python migrate.py; then
    echo "[entrypoint] ERROR: migrate.py failed; refusing to start app" >&2
    exit 1
fi

echo "[entrypoint] starting app: $*"
exec "$@"
