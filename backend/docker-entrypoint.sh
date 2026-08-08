#!/bin/sh
# Entrypoint for the Asto backend container.
#
# Pre-warms the query-embedding model in a short-lived process before uvicorn
# starts. fastembed only trusts a cache that it populated itself; a baked image
# cache uses a different on-disk metadata layout and is therefore re-downloaded
# on the first request. That re-download (~60MB) inside the 200MB-capped
# uvicorn process spikes memory and is killed mid-stream (ERR_EMPTY_RESPONSE).
# Running the download in a tiny `python -c` first lets it succeed and writes
# a trusted cache, so the long-running server reuses it without re-downloading.
set -e

echo "asto-backend: pre-warming embedding model..."
if python -c "from app.search.pgvector_search import _get_embedding_model; _get_embedding_model()" 2>&1; then
  echo "asto-backend: embedding model ready."
else
  echo "asto-backend: WARNING — embedding warmup failed; first request may retry." >&2
fi

exec uvicorn "$@"