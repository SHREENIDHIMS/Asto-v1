"""Metadata extraction from document content.

Extracts document-level metadata such as title, document type, and
department from file name, content headers, and structural patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.documents.text_extraction import ExtractedText


@dataclass
class DocumentMetadata:
    title: str
    doc_type: str = "policy"
    department: str = "general"
    source_path: str | None = None


_TITLE_PATTERNS = [
    re.compile(r"^(.*?)\s*—\s*", re.MULTILINE),
    re.compile(r"^#\s+(.+)$", re.MULTILINE),
]

_DOC_TYPE_KEYWORDS = {
    "underwriting": "underwriting",
    "eligibility": "eligibility",
    "compliance": "compliance",
    "policy": "policy",
    "procedure": "procedure",
    "guideline": "policy",
    "requirement": "policy",
}


def extract_metadata(
    extracted: ExtractedText, file_path: str | Path
) -> DocumentMetadata:
    """Infer metadata from file path and initial content lines."""
    path = Path(file_path)
    title = _guess_title(extracted, path)
    doc_type = _guess_doc_type(extracted)
    source_path = str(path)

    return DocumentMetadata(
        title=title,
        doc_type=doc_type,
        source_path=source_path,
    )


def _guess_title(extracted: ExtractedText, path: Path) -> str:
    lines = [l.strip() for l in extracted.text.split("\n") if l.strip()][:5]
    for line in lines:
        if len(line.split()) <= 12 and not line.islower():
            return line
    if lines:
        return lines[0][:80]
    return path.stem


def _guess_doc_type(extracted: ExtractedText) -> str:
    first_lines = extracted.text.lower()[:2000]
    for keyword, doc_type in _DOC_TYPE_KEYWORDS.items():
        if keyword in first_lines:
            return doc_type
    return "policy"
