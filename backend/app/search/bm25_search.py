"""BM25 full-text search using PostgreSQL's built-in tsvector/ts_rank.

No external search engine needed — Postgres handles both BM25 scoring
and vector search in the same query.
"""

from __future__ import annotations

import re
from typing import Sequence

# Strip punctuation and normalize for tsquery
_TSQUERY_CLEAN_RE = re.compile(r"[^a-zA-Z0-9\s]")


def build_tsquery(text: str) -> str:
    """Convert a search string into a PostgreSQL tsquery expression.

    Uses OR-joined prefix matching for retrieval so any matching term
    brings a chunk into the candidate set ('credit score' matches
    'credit scoring rules'). Ranking weights are applied separately
    via ts_rank_cd, so retrieval can favour recall while ordering
    stays relevance-driven.
    """
    cleaned = _TSQUERY_CLEAN_RE.sub(" ", text.lower()).strip()
    terms = cleaned.split()
    if not terms:
        return "''::tsquery"

    # OR-joined prefix matching: retrieve anything that matches any term
    prefix_terms = [f"{t}:*" for t in terms]
    return " | ".join(prefix_terms)
