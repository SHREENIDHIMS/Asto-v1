#!/usr/bin/env bash
#
# M5 — data retention pass (one-shot batch job).
#
# Deletes rows older than the configured per-table retention (audit-logged)
# and reports what was pruned. Runs via asto-retention.timer on the shared
# host; never inside the FastAPI process (rule 5). Pass --dry-run to report
# without deleting.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting retention pass"
python -m scripts.retention "$@"
echo "[$(date -Iseconds)] Retention pass complete"