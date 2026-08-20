"""Document upload API endpoint.

Per CLAUDE.md rule 5: validates and writes to storage/pending/ only.
Does NOT call ingestion logic. Ingestion runs separately via
infra/scripts/run_ingestion.sh → app.documents.ingest_batch
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth.permissions import require_role
from app.config import settings
from app.dependencies import require_auth
from app.documents.validation import read_upload, validate_upload

router = APIRouter()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
) -> dict:
    """Receive a document upload, validate, write to storage/pending/.

    Returns immediately — ingestion happens in a separate batch process.
    """
    require_role(user, "admin")

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    file_size, content = await read_upload(file)

    result = validate_upload(file.filename, file_size)
    if not result.valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    pending_dir = Path(settings.storage_pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{result.filename}"
    dest = pending_dir / unique_name
    dest.write_bytes(content)

    return {
        "message": "File uploaded successfully",
        "filename": result.filename,
        "stored_as": str(dest),
        "size_bytes": file_size,
    }