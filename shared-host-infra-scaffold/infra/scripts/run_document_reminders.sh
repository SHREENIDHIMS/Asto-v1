#!/usr/bin/env bash
#
# Runs the client document reminder emails as a one-shot batch job.
#
# Emails every active client their outstanding document checklist items.
#
# Deliberately does NOT run inside the FastAPI process (rule 5) — a
# one-shot script, triggered by asto-doc-reminders.timer. Call it from the
# timer or manually; never from app.main.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting document reminders"
python -m scripts.document_reminders
echo "[$(date -Iseconds)] Document reminders complete"
