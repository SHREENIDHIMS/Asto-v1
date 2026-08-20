"""Heuristic PII scanner (Phase I6, batch-only per CLAUDE.md rule 5).

Flags likely sensitive data in extracted document text so the admin review
queue can gate "publish anyway" on explicit confirmation. This is deliberately
a conservative regex heuristic — no LLM — so it never blocks ingestion and
only ever adds a flag column, never redacts stored content.

Coverage (2026-08-20 hardening): added phone numbers, Luhn-validated credit
card numbers, undashed SSNs, and ABA routing numbers (check-digit validated);
the US-address pattern was rewritten to drop the ambiguous inner character
classes that enabled pathological backtracking (ReDoS).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Real bcrypt-free helpers -----------------------------------------------------


def _digits(text: str) -> str:
    """Strip every non-digit from ``text``."""
    return re.sub(r"\D", "", text)


def _luhn_ok(digits: str) -> bool:
    """True when ``digits`` (13-19 digits) passes the Luhn checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _aba_ok(digits: str) -> bool:
    """True when ``digits`` is a 9-digit ABA routing number (check digit)."""
    if len(digits) != 9:
        return False
    if digits[:2] == "00":
        return False
    total = (
        3 * (int(digits[0]) + int(digits[3]) + int(digits[6]))
        + 7 * (int(digits[1]) + int(digits[4]) + int(digits[7]))
        + (int(digits[2]) + int(digits[5]) + int(digits[8]))
    )
    return total % 10 == 0


def _ssn_nodash_ok(digits: str) -> bool:
    """True when ``digits`` is a plausible 9-digit SSN (no 000/666/9xx area,
    no 00 group, no 0000 serial)."""
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    return (
        area not in {"000", "666"}
        and int(area) < 900
        and group != "00"
        and serial != "0000"
    )


def _classify_nine_digit(text: str) -> str | None:
    """Classify a bare 9-digit run as an undashed SSN or ABA routing number."""
    digits = _digits(text)
    if _ssn_nodash_ok(digits):
        return "ssn_nodash"
    if _aba_ok(digits):
        return "aba_routing"
    return None


def _classify_card(text: str) -> str | None:
    """Return 'credit_card' for a Luhn-valid card-like digit run, else None."""
    digits = _digits(text)
    if len(digits) in range(13, 20) and _luhn_ok(digits):
        return "credit_card"
    return None


@dataclass(frozen=True)
class _Pattern:
    kind: str
    pattern: re.Pattern[str]
    # Optional classifier returning the kind to emit, or None to skip.
    classify: Callable[[str], str | None] | None = None


_Patterns: list[_Pattern] = [
    _Pattern("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    _Pattern("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # One 9-digit pattern; the classifier emits ssn_nodash or aba_routing.
    _Pattern("id_number", re.compile(r"\b\d{9}\b"), _classify_nine_digit),
    _Pattern("credit_card", re.compile(r"\b(?:\d[ -]?){13,19}\b"), _classify_card),
    _Pattern(
        "phone",
        re.compile(r"\b(?:\+?1[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b"),
    ),
    _Pattern("dob", re.compile(r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/\d{4}\b")),
    # Street/city/state classes deliberately exclude the commas so the `+`
    # quantifiers cannot backtrack over their own delimiters.
    _Pattern(
        "us_address",
        re.compile(
            r"\b\d{1,5}\s+[A-Za-z0-9 .'-]+,\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b"
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
    for entry in _Patterns:
        for m in entry.pattern.finditer(text):
            kind = entry.kind if entry.classify is None else entry.classify(m.group(0))
            if kind:
                matches.append(PiiMatch(kind=kind, match=m.group(0), start=m.start(), end=m.end()))
    return matches


def has_pii(text: str) -> bool:
    """True if ``text`` contains any likely PII."""
    return any(scan_for_pii(text))


def flagged_kinds(text: str) -> list[str]:
    """Distinct PII kinds present in ``text``, in first-match order."""
    seen: list[str] = []
    for m in scan_for_pii(text):
        if m.kind not in seen:
            seen.append(m.kind)
    return seen