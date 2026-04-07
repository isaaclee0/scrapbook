#!/usr/bin/env bash
# Import the project SQL dump into the Docker MariaDB service, then assign all app
# data to isaac@leemail.com.au (see sqldumps/reassign_isaac.sql).
#
# Default dump file: sqldumps/20260406.sql
#
# Usage (from repo root):
#   1. Place the dump at sqldumps/20260406.sql (or pass another path as the last argument).
#   2. docker compose up -d db
#   3. ./scripts/import_sqldump_docker.sh
#      ./scripts/import_sqldump_docker.sh --fresh
#      ./scripts/import_sqldump_docker.sh path/to/other.sql
#      ./scripts/import_sqldump_docker.sh --fresh path/to/other.sql
#
# --fresh  Drops and recreates the target database before import (use when tables already
#          exist from docker init.sql or a failed import — fixes ERROR 1050).
#
# Alternative: docker compose down -v && docker compose up -d db  (wipes entire volume)
#
# Dumps with no USE/database line: import uses default schema DB_NAME (default: db).
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d sqldumps ]]; then
  echo "Missing sqldumps/ directory. Create it and add your .sql file(s)." >&2
  exit 1
fi

# Load passwords from .env when present
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ROOT_PW="${MYSQL_ROOT_PASSWORD:-scrapbook_local_root_dev}"
# Must match app DB_NAME / docker-compose MYSQL_DATABASE (dumps without USE db need this)
TARGET_DB="${DB_NAME:-db}"

FRESH=0
while [[ "${1:-}" =~ ^- ]]; do
  case "$1" in
    --fresh|-f) FRESH=1; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/import_sqldump_docker.sh [--fresh|-f] [dump.sql]

  --fresh, -f   Drop and recreate the DB_NAME database (default: db) before import.
                Use when ERROR 1050 (table already exists) or after docker init.sql.

  dump.sql      Optional path; default is sqldumps/20260406.sql
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1 (try --fresh or --help)" >&2
      exit 1
      ;;
  esac
done

if [[ "${1:-}" ]]; then
  DUMP_FILE="$1"
  if [[ ! -f "$DUMP_FILE" ]]; then
    echo "Dump file not found: $DUMP_FILE" >&2
    exit 1
  fi
else
  DUMP_FILE="sqldumps/20260406.sql"
  if [[ ! -f "$DUMP_FILE" ]]; then
    echo "Expected dump not found: $DUMP_FILE" >&2
    echo "Copy your export to that path, or run: $0 path/to/your.sql" >&2
    exit 1
  fi
fi

if ! docker compose exec -T db mariadb -uroot -p"$ROOT_PW" -e "SELECT 1" >/dev/null 2>&1; then
  echo "Cannot reach MariaDB as root. Is the db service up? Try: docker compose up -d db" >&2
  echo "If the password differs, set MYSQL_ROOT_PASSWORD in .env to match docker-compose." >&2
  exit 1
fi

echo "Using MariaDB root user to import (needed for CREATE DATABASE / DEFINER in many dumps)."
if [[ "$FRESH" -eq 1 ]]; then
  echo "(--fresh) Dropping and recreating database \`$TARGET_DB\` (all data in that schema will be removed)..."
  docker compose exec -T db mariadb -uroot -p"$ROOT_PW" -e \
    "DROP DATABASE IF EXISTS \`${TARGET_DB}\`; CREATE DATABASE \`${TARGET_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
else
  echo "Ensuring database \`$TARGET_DB\` exists (fixes ERROR 1046 when dump has no USE statement)..."
  docker compose exec -T db mariadb -uroot -p"$ROOT_PW" -e \
    "CREATE DATABASE IF NOT EXISTS \`${TARGET_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
fi

echo "Importing into \`$TARGET_DB\`: $DUMP_FILE"
docker compose exec -T db mariadb -uroot -p"$ROOT_PW" "$TARGET_DB" <"$DUMP_FILE"

if [[ ! -f sqldumps/reassign_isaac.sql ]]; then
  echo "Warning: sqldumps/reassign_isaac.sql missing; skipping user reassignment." >&2
  exit 0
fi

echo "Applying user reassignment (isaac@leemail.com.au)..."
docker compose exec -T db mariadb -uroot -p"$ROOT_PW" "$TARGET_DB" <sqldumps/reassign_isaac.sql

echo "Done. Start the app with: docker compose up -d"
echo "Log in with isaac@leemail.com.au (request OTP / magic link as usual)."
