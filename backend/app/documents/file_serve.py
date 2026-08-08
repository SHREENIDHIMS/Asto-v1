"""Resolve stored document files for authenticated serving.

Documents are stored on disk under ``storage/pending/`` (after upload)
and moved to ``storage/processed/`` by the ingestion batch. The
``documents.source_path`` column records the path at ingestion time,
which is the pre-move (pending) path, so it cannot be used verbatim.

This helper resolves a file by its basename across both storage
directories (processed first, then pending), which is safe because
``ingest_batch._move_to_processed`` preserves the filename.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from app.config import settings


def resolve_stored_file(source_path: str | None) -> Path:
    """Return a Path to the stored file for a document row.

    Searches processed/, then pending/. Raises 404 if not found.
    """
    if not source_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document has no stored file",
        )

    filename = Path(source_path).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document has no stored file",
        )

    for directory in (settings.storage_processed_dir, settings.storage_pending_dir):
        candidate = Path(directory) / filename
        if candidate.is_file():
            return candidate

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Stored file not found on disk ({filename})",
    )
