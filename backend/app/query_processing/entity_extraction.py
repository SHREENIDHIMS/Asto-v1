"""Deterministic, dictionary-based entity extraction (query-time).

Replaces the originally-planned GLiNER model at query time: a domain
term dictionary + numeric patterns is far lighter (~0 MB, microseconds)
and sufficient for domain questions. GLiNER was evaluated as not
worth the RAM/CPU on the shared 1 GiB host.

Extracted entity types: lender, product, document, property, metric,
process, status, amount, percentage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.query_processing import domain_terms

_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")
_PERCENT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%")

# One regex per alias is wasteful; build one alternation regex per alias
# length bucket so multi-word aliases match as units.
_ALIAS_PATTERNS: dict[int, re.Pattern] = {}


def _alias_pattern(word_count: int) -> re.Pattern:
    pattern = _ALIAS_PATTERNS.get(word_count)
    if pattern is None:
        aliases = [a for a in domain_terms.aliases() if a.count(" ") + 1 == word_count]
        joined = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
        pattern = re.compile(rf"\b(?:{joined})\b")
        _ALIAS_PATTERNS[word_count] = pattern
    return pattern


@dataclass
class Entity:
    canonical: str
    term_type: str
    matched: str
    start: int
    end: int


def extract_entities(text: str) -> list[Entity]:
    """Extract domain entities and numeric values from a lowercased query.

    Returns entities in order of appearance. The caller should treat
    these as *hints* — the search itself still runs on the full text.
    """
    entities: list[Entity] = []
    text = text or ""

    # Numeric patterns first (they don't collide with the dictionary).
    for m in _PERCENT_RE.finditer(text):
        entities.append(Entity("percentage", "percentage", m.group(0), m.start(), m.end()))
    for m in _AMOUNT_RE.finditer(text):
        entities.append(Entity("amount", "amount", m.group(0), m.start(), m.end()))

    max_words = 3
    used: set[tuple[int, int]] = set()
    for word_count in range(max_words, 0, -1):
        for m in _alias_pattern(word_count).finditer(text):
            if any(not (m.end() <= s or m.start() >= e) for s, e in used):
                continue  # overlap with a longer match already captured
            alias = m.group(0)
            canonical = domain_terms.canonical_of(alias)
            term_type = domain_terms.type_of(alias) or "term"
            entities.append(Entity(canonical, term_type, alias, m.start(), m.end()))
            used.add((m.start(), m.end()))

    entities.sort(key=lambda e: (e.start, -e.end))
    return entities


def unique_canonicals(entities: list[Entity]) -> list[str]:
    """Canonical terms in first-seen order (for expansion)."""
    seen: set[str] = set()
    out: list[str] = []
    for e in entities:
        if e.canonical not in seen and e.term_type != "percentage" and e.term_type != "amount":
            seen.add(e.canonical)
            out.append(e.canonical)
    return out
