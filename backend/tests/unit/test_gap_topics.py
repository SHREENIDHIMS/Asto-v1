"""Unit tests for recurring knowledge-gap topic clustering."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.knowledge_gap.topics import (
    TopicConfig,
    cluster_gap_topics,
    extract_significant_tokens,
)


def _conn(rows: list[dict]) -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = rows
    return conn


class TestExtractSignificantTokens:
    def test_drops_stopwords_and_short_tokens(self):
        tokens = extract_significant_tokens("What is the APR for escrow?")
        assert "what" not in tokens and "the" not in tokens and "for" not in tokens
        assert "apr" not in tokens  # < min_token_len (4)
        assert tokens == ["escrow"]

    def test_dedupes_within_query(self):
        assert extract_significant_tokens("escrow escrow ESCROW waiver") == [
            "escrow", "waiver",
        ]


class TestClusterGapTopics:
    def test_topics_require_min_queries_and_are_ordered(self):
        rows = (
            [{"query": f"escrow question {i}", "times": 1} for i in range(4)]
            + [{"query": f"title insurance thing {i}", "times": 1} for i in range(3)]
            + [{"query": "one off query", "times": 1}]
        )
        report = cluster_gap_topics(_conn(rows), TopicConfig(min_queries=3))

        topics = report["topics"]
        assert topics[0]["topic"] == "escrow"
        assert topics[0]["query_count"] == 4
        assert {t["topic"] for t in topics} == {
            "escrow", "question", "title", "insurance", "thing",
        }
        # 'one'/'off'/'query' appear once — below threshold.
        assert all(t["topic"] != "query" for t in topics)
        assert report["total_gaps"] == 8
        assert report["distinct_queries"] == 8

    def test_samples_are_verbatim_and_capped(self):
        rows = [{"query": f"appraisal delay variant {i}", "times": 2}
                for i in range(7)]
        report = cluster_gap_topics(_conn(rows), TopicConfig(min_queries=3))
        topic = report["topics"][0]
        assert len(topic["samples"]) == 5
        assert topic["samples"][0] == "appraisal delay variant 0"
        assert topic["gap_hits"] == 14

    def test_empty_window(self):
        report = cluster_gap_topics(_conn([]))
        assert report["topics"] == []
        assert report["total_gaps"] == 0
