"""Checklist chunker for document ingestion.

Keeps checklist items (bullet points, numbered lists) as
individual chunks so each item is independently searchable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from app.documents.text_extraction import ExtractedText


@dataclass
class ChecklistChunk:
    content: str
    section: str | None
    chunk_type: str = "checklist"
    page_number: int | None = None


def chunk_checklist(text: str, section: str | None = None, page_number: int | None = None) -> Iterator[ChecklistChunk]:
    """Yield individual checklist items from a text block.

    Detects bullet points (-, *, +) and numbered lists (1., 2., etc.)
    and splits them into separate chunks. Only yields chunks if at least
    one list item is detected — plain paragraphs are not treated as
    checklists.
    """
    lines = text.split("\n")
    current_item: list[str] = []
    found_any = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_item and found_any:
                yield ChecklistChunk(
                    content="\n".join(current_item),
                    section=section,
                    chunk_type="checklist",
                    page_number=page_number,
                )
                current_item = []
            continue

        if _is_list_item(stripped):
            found_any = True
            if current_item and found_any:
                yield ChecklistChunk(
                    content="\n".join(current_item),
                    section=section,
                    chunk_type="checklist",
                    page_number=page_number,
                )
            current_item = [stripped]
        else:
            current_item.append(stripped)

    if current_item and found_any:
        yield ChecklistChunk(
            content="\n".join(current_item),
            section=section,
            chunk_type="checklist",
            page_number=page_number,
        )


def _is_list_item(line: str) -> bool:
    """Check if a line is a list item (bullet or numbered)."""
    return bool(
        re.match(r"^[\-\*]\s", line)
        or re.match(r"^\d+[\.\)]\s", line)
    )