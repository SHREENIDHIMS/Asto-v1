#!/usr/bin/env bash
#
# Runs the J5 no-answer / low-confidence spike report as a one-shot batch job.
#
# Aggregates the last 24h of audit_log and, when the weak-outcome rate
# crosses the configured threshold, inserts a notification row for admins.
#
# Deliberately does NOT run inside the FastAPI process (rule 5) — a
# one-shot script, triggered by asto-report-gaps.timer. Call it from
# the timer or manually; never from app.main.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting no-answer spike report"
python -m scripts.report_gaps
echo "[$(date -Iseconds)] Spike report complete"
