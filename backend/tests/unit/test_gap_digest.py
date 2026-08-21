"""Unit tests for the weekly knowledge-gap digest (batch-only module)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.knowledge_gap.digest import (
    GapDigestConfig,
    collect_digest,
    email_digest,
    render_digest_text,
)


def _conn(rows_by_call: list[list[dict]], fetchone_queue: list[dict] | None = None):
    """A connection whose cursor.fetchall/fetchone return queued values."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    fetchall_batches = iter(rows_by_call)
    fetchone_values = iter(fetchone_queue or [])

    def fetchall_side():
        try:
            return next(fetchall_batches)
        except StopIteration:
            return []

    def fetchone_side():
        return next(fetchone_values)

    cur.fetchall.side_effect = fetchall_side
    cur.fetchone.side_effect = fetchone_side
    return conn, cur


class TestCollectDigest:
    def test_aggregates_gaps_and_weak_outcomes(self):
        conn, cur = _conn(
            [
                [   # top queries
                    {"query": "escrow waiver", "times": 4, "last_seen": None},
                    {"query": "apr cap", "times": 2, "last_seen": None},
                ],
            ],
            fetchone_queue=[
                {"total": 12, "distinct_q": 5},  # gap totals
                {"total": 40, "weak": 9},        # weak outcomes
            ],
        )
        report = collect_digest(conn, GapDigestConfig(window_days=7, top_n=10))
        assert report["total_gaps"] == 12
        assert report["distinct_queries"] == 5
        assert report["top_queries"][0]["query"] == "escrow waiver"
        assert report["top_queries"][0]["times"] == 4
        assert report["weak"] == {"total": 40, "count": 9, "rate": 0.225}
        # Window params must reach every statement.
        assert all("make_interval" in c.args[0] for c in cur.execute.call_args_list)

    def test_empty_window(self):
        conn, _ = _conn(
            [],
            fetchone_queue=[
                {"total": 0, "distinct_q": 0},
                {"total": 0, "weak": 0},
            ],
        )
        report = collect_digest(conn)
        assert report["total_gaps"] == 0
        assert report["top_queries"] == []
        assert report["weak"]["rate"] == 0.0


class TestRenderDigestText:
    def test_includes_verbatim_queries_and_counts(self):
        report = {
            "window_days": 7,
            "total_gaps": 6,
            "distinct_queries": 3,
            "top_queries": [
                {"query": "escrow waiver", "times": 4, "last_seen": None},
                {"query": "apr cap", "times": 2, "last_seen": None},
            ],
            "weak": {"total": 20, "count": 5, "rate": 0.25},
        }
        subject, text, html = render_digest_text(report)
        assert "6 gaps" in subject
        assert "escrow waiver" in text and "apr cap" in text
        assert "4x" in text
        assert "<li>escrow waiver (4x)</li>" in html

    def test_empty_digest_has_no_gap_section(self):
        report = {
            "window_days": 7,
            "total_gaps": 0,
            "distinct_queries": 0,
            "top_queries": [],
            "weak": {"total": 0, "count": 0, "rate": 0.0},
        }
        subject, text, html = render_digest_text(report)
        assert "No knowledge gaps" in text
        assert "No knowledge gaps" in html


class TestEmailDigest:
    def test_sends_to_all_active_admins(self):
        conn, _ = _conn(
            [],
            fetchone_queue=[],
        )
        # email_digest uses fetchall for the admin list.
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = None
        cur.fetchall.return_value = [
            {"email": "a@asto.local"},
            {"email": "b@asto.local"},
        ]
        report = {
            "window_days": 7,
            "total_gaps": 1,
            "distinct_queries": 1,
            "top_queries": [],
            "weak": {"total": 2, "count": 1, "rate": 0.5},
        }
        with patch("app.email.mailer.send_email", return_value=True) as mock_send:
            sent = email_digest(conn, report)
        assert sent == 2
        assert mock_send.call_count == 2
        recipients = [c.args[0] for c in mock_send.call_args_list]
        assert recipients == ["a@asto.local", "b@asto.local"]
