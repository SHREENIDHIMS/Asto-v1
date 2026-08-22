"""Matched-term extraction for search-result highlighting (J1).

Lexical token overlap between the query and a retrieved chunk/sentence —
deliberately dependency-free: no ``ts_headline``, no stemming. Terms are
lower-cased, split on non-word characters, and matched as whole tokens so
the frontend can highlight them safely client-side. Keeping the match
faithful to the exact query words also avoids over-highlighting short
substring collisions (e.g. "lo" inside "loan").
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*")

# Stopwords are dropped so highlights stay on content words, not glue.
# Mirrors the English stopword list Postgres uses for tsvector/ts_headline.
_STOPWORDS = frozenset({
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "but", "by", "can", "could", "did",
    "do", "does", "for", "from", "had", "has", "have", "he", "her", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "me", "more", "my",
    "no", "not", "of", "on", "or", "our", "shall", "she", "should", "so",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "to", "too", "up", "us", "was", "we", "were", "what",
    "when", "where", "which", "who", "why", "will", "with", "would", "you",
    "your",
})


def query_terms(query_text: str) -> list[str]:
    """Lower-cased query tokens in order of first appearance."""
    return _WORD_RE.findall(query_text.lower())


def significant_query_terms(query_text: str) -> list[str]:
    """Unique content terms of the query (stopwords removed), in order of
    first appearance. This is the denominator for term-coverage signals."""
    terms: list[str] = []
    seen: set[str] = set()
    for term in query_terms(query_text):
        if term in seen or term in _STOPWORDS:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def matched_terms(query_text: str, text: str) -> list[str]:
    """Return the unique query terms that occur as words in ``text``.

    Case-insensitive, ordered by first appearance in the query. Terms that
    do not appear are omitted, so an excerpt only carries the terms that
    actually explain why it matched. Stopwords are excluded so client-side
    highlights focus on content words.
    """
    text_words = set(_WORD_RE.findall(text.lower()))
    terms: list[str] = []
    seen: set[str] = set()
    for term in query_terms(query_text):
        if term in seen or term in _STOPWORDS:
            continue
        seen.add(term)
        if term in text_words:
            terms.append(term)
    return terms
