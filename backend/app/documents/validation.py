"""Validation for uploaded documents.

Checks file extension and size. Per CLAUDE.md rule 5, the API endpoint
only validates — it does not ingest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import settings

ALLOWED_EXTENSIONS: set[str] = {
    ".pdf", ".txt", ".docx", ".html", ".htm", ".md",
    ".csv", ".xlsx", ".pptx", ".odt", ".rtf", ".epub",
}

_KB = 1024
_MB = 1024 * 1024


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable size (e.g. 5.5 MB)."""
    if size_bytes >= _MB:
        value = f"{size_bytes / _MB:.1f}"
        return f"{value.rstrip('0').rstrip('.')} MB"
    if size_bytes >= _KB:
        value = f"{size_bytes / _KB:.1f}"
        return f"{value.rstrip('0').rstrip('.')} KB"
    return f"{size_bytes} B"


@dataclass
class ValidationResult:
    valid: bool
    filename: str
    error: str | None
    file_size: int


def validate_upload(filename: str, file_size: int) -> ValidationResult:
    """Validate a file name and size against configured limits."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return ValidationResult(
            valid=False,
            filename=filename,
            error=f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            file_size=file_size,
        )
    if file_size > settings.max_upload_bytes:
        limit = _human_size(settings.max_upload_bytes)
        return ValidationResult(
            valid=False,
            filename=filename,
            error=(
                f"Your file is too big ({_human_size(file_size)}). "
                f"The maximum upload size is {limit}. "
                f"Please upload a file smaller than {limit}."
            ),
            file_size=file_size,
        )
    return ValidationResult(
        valid=True,
        filename=filename,
        error=None,
        file_size=file_size,
    )
