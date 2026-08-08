"""Lightweight intent detection.

Classifies a sub-query into a coarse intent bucket used for:
- the response's intent label,
- a small metadata (doc_type) boost in ranking,
- evaluation analysis.

Pure keyword matching — deterministic, zero dependencies.
"""

from __future__ import annotations

import re

from app.query_processing import domain_terms
from app.query_processing.entity_extraction import Entity

_WORD_RE = re.compile(r"[a-z]+")


def detect_intent(text: str, entities: list[Entity]) -> str:
    """Return the dominant intent for a sub-query.

    Precedence: costs > limits > documents > eligibility > requirements
    > process > definition > general.
    """
    words = set(_WORD_RE.findall(text))
    lower = text.lower()

    if any(e.term_type == "metric" and e.canonical in ("annual percentage rate", "private mortgage insurance", "mortgage insurance premium") for e in entities):
        if words & domain_terms.INTENT_KEYWORDS["costs"]:
            return "costs"
    if "loan to value" in [e.canonical for e in entities]:
        if words & domain_terms.INTENT_KEYWORDS["limits"]:
            return "limits"

    for intent in ("costs", "limits", "documents", "eligibility", "requirements", "process", "definition"):
        kws = domain_terms.INTENT_KEYWORDS[intent]
        if any(kw in lower for kw in kws):
            return intent

    if any(e.term_type == "document" for e in entities):
        return "documents"
    if any(e.term_type == "metric" for e in entities):
        return "requirements"
    if any(e.term_type == "property" or e.term_type == "lender" for e in entities):
        return "eligibility"
    return "general"


def doc_type_boost(intent: str) -> set[str]:
    """doc_types to boost for a given intent (may be empty)."""
    return domain_terms.INTENT_DOC_TYPE_BOOST.get(intent, set())
