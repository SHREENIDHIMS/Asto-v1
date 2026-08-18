"""Heuristic PII scanner (Phase I6, batch-only per CLAUDE.md rule 5).

Flags likely sensitive data in extracted document text so the admin review
queue can gate "publish anyway" on explicit confirmation. This is deliberately
a conservative regex heuristic — no LLM — so it never blocks ingestion and
only ever adds a flag column, never redacts stored content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_Patterns: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("dob", re.compile(r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/\d{4}\b")),
    (
        "us_address",
        re.compile(
            r"\b\d{1,5}\s+[A-Za-z0-9 .,'-]+,\s*[A-Za-z .,'-]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?\b"
        ),
    ),
]


@dataclass(frozen=True)
class PiiMatch:
    kind: str
    match: str
    start: int
    end: int


def scan_for_pii(text: str) -> list[PiiMatch]:
    """Return every likely-PII span found in ``text``."""
    if not text:
        return []
    matches: list[PiiMatch] = []
    for kind, pattern in _Patterns:
        for m in pattern.finditer(text):
            matches.append(PiiMatch(kind=kind, match=m.group(0), start=m.start(), end=m.end()))
    return matches


def has_pii(text: str) -> bool:
    """True if ``text`` contains any likely PII."""
    return any(scan_for_pii(text))


def flagged_kinds(text: str) -> list[str]:
    """Distinct PII kinds present in ``text`` (ordered by pattern)."""
    seen: list[str] = []
    for kind, _ in _Patterns:
        if any(m.kind == kind for m in scan_for_pii(text)):
            seen.append(kind)
    return seen
