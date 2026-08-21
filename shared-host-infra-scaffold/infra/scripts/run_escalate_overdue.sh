#!/usr/bin/env bash
#
# Runs the overdue task/workflow escalation as a one-shot batch job.
#
# Notifies assignees of overdue tasks and workflows (24h per-item cooldown).
#
# Deliberately does NOT run inside the FastAPI process (rule 5) — a
# one-shot script, triggered by asto-escalate-overdue.timer.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting overdue escalation"
python -m scripts.escalate_overdue
echo "[$(date -Iseconds)] Overdue escalation complete"
