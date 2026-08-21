"""Recurring knowledge-gap topics (deterministic token clustering).

Groups the window's ``knowledge_gaps`` queries by shared significant
tokens so admins can see *what* the knowledge base keeps failing to
answer. This is honest counting, not AI: tokens are lowercased words of
4+ characters minus a small stopword list; a "topic" is any such token
appearing in at least ``min_queries`` distinct gap queries.

Read-only analysis consumed by ``GET /admin/gap-topics`` (analytics) —
no LLM, no generated text, every sample query is verbatim from the log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small English stopword list — enough to keep topics meaningful without
# pretending to be an NLP pipeline.
STOPWORDS = frozenset({
    "the", "and", "for", "with", "what", "when", "where", "which", "who",
    "how", "does", "did", "can", "could", "should", "would", "will",
    "into", "from", "that", "this", "there", "their", "have", "has",
    "are", "was", "were", "been", "being", "about", "after", "before",
    "need", "needs", "want", "get", "got", "does", "any", "all", "you",
    "your", "our", "his", "her", "its", "not", "but", "out", "more",
    "some", "than", "then", "them", "these", "those", "over", "under",
    "please", "tell", "show", "find", "give", "make", "made", "also",
})


@dataclass
class TopicConfig:
    """Clustering knobs (rule 7: configuration, not constants)."""

    window_days: int = 30
    min_queries: int = 3     # topic must appear in >= N distinct queries
    top_n: int = 10          # max topics returned
    min_token_len: int = 4


def extract_significant_tokens(query: str, config: TopicConfig | None = None) -> list[str]:
    """Lowercased alphanumeric tokens, stopwords and short words removed."""
    config = config or TopicConfig()
    tokens = _TOKEN_RE.findall(query.lower())
    seen: list[str] = []
    for t in tokens:
        if len(t) < config.min_token_len or t in STOPWORDS:
            continue
        if t not in seen:
            seen.append(t)
    return seen


def cluster_gap_topics(conn, config: TopicConfig | None = None) -> dict:
    """Cluster the window's gap queries by significant-token overlap.

    Returns ``{"window_days", "total_gaps", "distinct_queries",
    "topics": [{"topic", "query_count", "samples": [str, ...]}]}`` with
    topics ordered by query_count desc.
    """
    config = config or TopicConfig()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT query, COUNT(*) AS times "
            "FROM knowledge_gaps "
            "WHERE created_at >= now() - make_interval(days => %s) "
            "AND btrim(query) <> '' "
            "GROUP BY query ORDER BY times DESC, query ASC",
            (config.window_days,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    total_gaps = sum(int(r["times"]) for r in rows)
    distinct = len(rows)

    # Token -> set of query strings containing it.
    by_token: dict[str, list[dict]] = {}
    for row in rows:
        for token in extract_significant_tokens(row["query"], config):
            by_token.setdefault(token, []).append(row)

    topics = [
        {
            "topic": token,
            "query_count": len(members),
            "gap_hits": sum(int(m["times"]) for m in members),
            "samples": [
                m["query"] for m in members[:5]
            ],
        }
        for token, members in by_token.items()
        if len(members) >= config.min_queries
    ]
    topics.sort(key=lambda t: (-t["query_count"], t["topic"]))

    return {
        "window_days": config.window_days,
        "total_gaps": total_gaps,
        "distinct_queries": distinct,
        "topics": topics[: config.top_n],
    }
