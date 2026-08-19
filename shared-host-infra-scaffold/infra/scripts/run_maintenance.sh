#!/usr/bin/env bash
#
# M3 — scheduled pgvector/index maintenance (one-shot batch job).
#
# VACUUM ANALYZE the search tables and REINDEX the pgvector HNSW / FTS GIN
# indexes when dead-tuple bloat exceeds the threshold. Runs via
# asto-maintenance.timer on the shared host; never inside the FastAPI
# process (rule 5). Pass extra flags through, e.g. --dry-run.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting maintenance pass"
python -m scripts.maintenance "$@"
echo "[$(date -Iseconds)] Maintenance pass complete"