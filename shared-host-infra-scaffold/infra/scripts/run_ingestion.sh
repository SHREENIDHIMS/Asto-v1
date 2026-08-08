#!/usr/bin/env bash
#
# Runs the document ingestion pipeline (OCR, chunking, entity
# extraction, embedding generation, indexing) as a one-shot batch job.
#
# This deliberately does NOT run inside the FastAPI process. The
# embedding model is the heaviest component in the stack —
# loading it into the always-on API process means paying that RAM
# cost 24/7 even when nobody is uploading documents. Running it
# here means the memory is only held for the duration of the job.
#
# Trigger this manually, via cron, or via a lightweight upload-queue
# consumer — never call it from inside app.main directly.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting ingestion batch"
python -m app.documents.ingest_batch --queue-dir /opt/projects/asto/storage/pending
echo "[$(date -Iseconds)] Ingestion batch complete"

# Process exits here — the embedding model RAM is
# released back to the OS, not held resident.
