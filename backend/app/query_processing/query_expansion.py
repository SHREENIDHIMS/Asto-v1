"""Query expansion via the synonym/acronym dictionary.

Expands acronyms and aliases into their canonical phrase so that both
BM25 (exact-term matching) and the embedding model (dense semantics) see
richer text. The original terms are kept — expansion *adds* signal, it
never replaces the user's words.
"""

from __future__ import annotations

from app.query_processing import domain_terms
from app.query_processing.entity_extraction import Entity


def expand(text: str, entities: list[Entity]) -> str:
    """Return ``text`` with canonical phrases appended for matched terms.

    e.g. ``max ltv for investment properties`` ->
    ``max ltv for investment properties loan to value investment property``
    """
    parts = [text]
    seen: set[str] = set()
    for e in entities:
        if e.term_type in ("percentage", "amount"):
            continue
        if e.canonical in seen:
            continue
        # Don't append the canonical if the user already typed it verbatim.
        if e.canonical in text:
            seen.add(e.canonical)
            continue
        seen.add(e.canonical)
        parts.append(e.canonical)
    return " ".join(parts).strip()


def expansion_candidates(text: str) -> list[str]:
    """Aliases present in the text (for diagnostics/tests)."""
    return [a for a in domain_terms.aliases() if a in text]
