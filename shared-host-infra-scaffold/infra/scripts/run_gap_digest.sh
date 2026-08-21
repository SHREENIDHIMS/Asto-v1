#!/usr/bin/env bash
#
# Runs the weekly knowledge-gap digest as a one-shot batch job.
#
# Aggregates the last 7 days of knowledge_gaps + weak outcomes and emails
# a digest to every active admin via the shared mailer.
#
# Deliberately does NOT run inside the FastAPI process (rule 5) — a
# one-shot script, triggered by asto-gap-digest.timer. Call it from the
# timer or manually; never from app.main.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting knowledge-gap digest"
python -m scripts.gap_digest
echo "[$(date -Iseconds)] Knowledge-gap digest complete"
