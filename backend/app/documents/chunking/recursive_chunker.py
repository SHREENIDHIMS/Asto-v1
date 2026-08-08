"""Recursive chunker for large text blocks.

Splits oversized paragraphs into smaller chunks by sentence
boundaries, respecting a maximum token count per chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator


@dataclass
class RecursiveChunk:
    content: str
    section: str | None
    chunk_type: str = "paragraph"
    page_number: int | None = None


def recursive_chunk(
    text: str,
    max_tokens: int = 300,
    section: str | None = None,
    page_number: int | None = None,
) -> Iterator[RecursiveChunk]:
    """Recursively split text into chunks of at most max_tokens.

    Splits on sentence boundaries first, then on clause boundaries
    if sentences are still too long.
    """
    if not text.strip():
        return

    sentences = _split_sentences(text)
    current: list[str] = []

    for sentence in sentences:
        current.append(sentence)
        combined = " ".join(current)
        if _count_tokens(combined) >= max_tokens:
            if len(current) > 1:
                # Remove the last sentence and yield the rest
                current.pop()
                yield RecursiveChunk(
                    content=" ".join(current),
                    section=section,
                    chunk_type="paragraph",
                    page_number=page_number,
                )
                current = [sentence]
            else:
                # Single sentence exceeds max_tokens; split on clauses
                yield from _split_clause(
                    sentence,
                    max_tokens,
                    section=section,
                    page_number=page_number,
                )
                current = []

    if current:
        yield RecursiveChunk(
            content=" ".join(current),
            section=section,
            chunk_type="paragraph",
            page_number=page_number,
        )


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    return re.split(r"(?<=[.!?])\s+", text)


def _split_clause(
    sentence: str, max_tokens: int, section: str | None, page_number: int | None
) -> Iterator[RecursiveChunk]:
    """Split a long sentence on clause boundaries."""
    clauses = re.split(r"(?<=[,;])\s+", sentence)
    current: list[str] = []

    for clause in clauses:
        current.append(clause)
        if _count_tokens(" ".join(current)) >= max_tokens:
            if len(current) > 1:
                current.pop()
                yield RecursiveChunk(
                    content=" ".join(current),
                    section=section,
                    chunk_type="paragraph",
                    page_number=page_number,
                )
                current = [clause]
            else:
                yield RecursiveChunk(
                    content=clause,
                    section=section,
                    chunk_type="paragraph",
                    page_number=page_number,
                )
                current = []

    if current:
        yield RecursiveChunk(
            content=" ".join(current),
            section=section,
            chunk_type="paragraph",
            page_number=page_number,
        )


def _count_tokens(text: str) -> int:
    """Approximate token count (words * 1.3)."""
    return int(len(text.split()) * 1.3)