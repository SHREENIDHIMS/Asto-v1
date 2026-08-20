"""Validation for uploaded documents.

Checks file extension and size. Per CLAUDE.md rule 5, the API endpoint
only validates — it does not ingest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from app.config import settings

if TYPE_CHECKING:
    from starlette.datastructures import UploadFile

ALLOWED_EXTENSIONS: set[str] = {
    ".pdf", ".txt", ".docx", ".html", ".htm", ".md",
    ".csv", ".xlsx", ".pptx", ".odt", ".rtf", ".epub",
}

_KB = 1024
_MB = 1024 * 1024


def sanitize_filename(filename: str) -> str | None:
    """Return the safe basename of an uploaded file, or ``None`` if unsafe.

    Uploaders must never be able to influence the write path (a crafted
    ``../../../evil.pdf`` or ``..\\..\\evil.pdf`` would otherwise let an
    authenticated uploader write outside ``storage/pending/``). Reject any
    name that carries a path separator, a traversal component, or that
    resolves to something other than itself as a pure filename.
    """
    if not filename:
        return None
    if "/" in filename or "\\" in filename:
        return None
    name = PurePath(filename).name
    if name != filename or not name or name in (".", ".."):
        return None
    return name


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable size (e.g. 5.5 MB)."""
    if size_bytes >= _MB:
        value = f"{size_bytes / _MB:.1f}"
        return f"{value.rstrip('0').rstrip('.')} MB"
    if size_bytes >= _KB:
        value = f"{size_bytes / _KB:.1f}"
        return f"{value.rstrip('0').rstrip('.')} KB"
    return f"{size_bytes} B"


async def read_upload(file: "UploadFile", max_bytes: int | None = None) -> tuple[int, bytes]:
    """Stream an upload fully, aborting with 413 once it passes the cap.

    The alternative (buffering the whole body then validating) lets an
    attacker stream unlimited data and OOM the socket-activated single
    worker. The cap is checked on every chunk so the body is never fully
    buffered for oversized files.
    """
    cap = max_bytes if max_bytes is not None else settings.max_upload_bytes
    total = 0
    content = b""
    while chunk := await file.read(8192):
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Upload exceeds the {_human_size(cap)} maximum size.",
            )
        content += chunk
    return total, content


@dataclass
class ValidationResult:
    valid: bool
    filename: str
    error: str | None
    file_size: int


def validate_upload(filename: str, file_size: int) -> ValidationResult:
    """Validate a file name and size against configured limits."""
    safe = sanitize_filename(filename)
    if safe is None:
        return ValidationResult(
            valid=False,
            filename=filename,
            error=(
                "Filename is unsafe: it must be a plain file name without "
                "paths or '..' components."
            ),
            file_size=file_size,
        )
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return ValidationResult(
            valid=False,
            filename=safe,
            error=f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            file_size=file_size,
        )
    if file_size > settings.max_upload_bytes:
        limit = _human_size(settings.max_upload_bytes)
        return ValidationResult(
            valid=False,
            filename=safe,
            error=(
                f"Your file is too big ({_human_size(file_size)}). "
                f"The maximum upload size is {limit}. "
                f"Please upload a file smaller than {limit}."
            ),
            file_size=file_size,
        )
    return ValidationResult(
        valid=True,
        filename=safe,
        error=None,
        file_size=file_size,
    )
