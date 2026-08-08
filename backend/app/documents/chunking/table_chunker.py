"""Table chunker for document ingestion.

Keeps HTML/Markdown tables as single atomic chunks.
Never splits a table row across chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from app.documents.text_extraction import ExtractedText


@dataclass
class TableChunk:
    content: str
    section: str | None
    chunk_type: str = "table"
    page_number: int | None = None


def chunk_table(text: str, section: str | None = None, page_number: int | None = None) -> Iterator[TableChunk]:
    """Yield table chunks from a text block that contains a table.

    Detects markdown-style tables (pipes) and HTML tables.
    Each table is kept as a single chunk.
    """
    stripped = text.strip()
    if not stripped:
        return

    if _is_markdown_table(stripped):
        yield TableChunk(
            content=stripped,
            section=section,
            chunk_type="table",
            page_number=page_number,
        )
        return

    if _is_html_table(stripped):
        yield TableChunk(
            content=stripped,
            section=section,
            chunk_type="table",
            page_number=page_number,
        )
        return


def _is_markdown_table(text: str) -> bool:
    """Check if text looks like a markdown table (pipes and dashes)."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    has_pipes = any("|" in line for line in lines)
    has_separator = any(re.match(r"^[\|\s\-:]+$", line) for line in lines)
    return has_pipes and has_separator


def _is_html_table(text: str) -> bool:
    """Check if text contains an HTML table."""
    return bool(re.search(r"<table[\s>]", text, re.IGNORECASE))