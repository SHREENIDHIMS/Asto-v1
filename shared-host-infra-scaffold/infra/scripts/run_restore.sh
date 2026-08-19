#!/usr/bin/env bash
#
# M6 — restore an Asto database from a custom-format dump (manual, on-demand).
#
# NOT scheduled — a recovery action. Point it at a scratch/empty database for
# testing. Example:
#   ./run_restore.sh /opt/projects/asto/backend/storage/backups/asto_20260818_120000.dump
#
# If pg_restore is not on PATH (Postgres in Docker), set
#   ASTO_PGRESTORE_COMMAND="docker compose exec -T postgres pg_restore"
# and ensure the dump file is reachable inside that context.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

DUMP="${1:?usage: run_restore.sh <dump-file>}"
echo "[$(date -Iseconds)] Restoring $DUMP"
python -m scripts.restore_db "$DUMP"
echo "[$(date -Iseconds)] Restore complete"
