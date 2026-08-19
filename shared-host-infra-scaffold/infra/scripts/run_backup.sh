#!/usr/bin/env bash
#
# M6 — nightly rotating Postgres backup (one-shot batch job).
#
# Writes a custom-format pg_dump into storage/backups (rotating, keeps
# the newest ASTO_BACKUP_KEEP dumps). Runs via asto-backup.timer on the
# shared host; never inside the FastAPI process (rule 5).
#
# If pg_dump is not on PATH (e.g. Postgres runs in Docker), set
#   ASTO_PGDUMP_COMMAND="docker compose exec -T postgres pg_dump"
# so the wrapper is used and stdout is piped back to the host.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting database backup"
python -m scripts.backup_db
echo "[$(date -Iseconds)] Database backup complete"
