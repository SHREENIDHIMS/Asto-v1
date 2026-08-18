"""Tests for J5 — no-answer / low-confidence spike alerting.

Unit tests exercise the pure aggregation/threshold logic and the mocked
DB flow. DB-backed tests live in ``tests/integration/test_spike_alerting.py``
(the unit conftest autouse-mocks every ``acquire`` call).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.response.spike_alerting import (
    DEFAULT_SPIKE_ALERT,
    SpikeAlertConfig,
    compute_window_stats,
    run_spike_report,
    should_alert,
)


class TestComputeWindowStats:
    def test_all_answer_no_weak(self):
        assert compute_window_stats(["answer", "answer"]) == {
            "total": 2, "weak": 0, "rate": 0.0,
        }

    def test_mixed_window_rate(self):
        stats = compute_window_stats(["answer", "no_answer", "partial", "answer"])
        assert stats["total"] == 4
        assert stats["weak"] == 2
        assert stats["rate"] == 0.5

    def test_empty_window(self):
        stats = compute_window_stats([])
        assert stats["total"] == 0
        assert stats["weak"] == 0
        assert stats["rate"] == 0.0

    def test_no_sub_queries_not_weak(self):
        """no_sub_queries is a candidate gap, not a routed weak outcome."""
        stats = compute_window_stats(["no_sub_queries", "answer"])
        assert stats["weak"] == 0


class TestShouldAlert:
    def test_triggers_above_rate(self):
        config = SpikeAlertConfig(min_queries=5, spike_rate=0.4)
        assert should_alert({"total": 10, "weak": 5, "rate": 0.5}, config) is True

    def test_below_rate(self):
        config = SpikeAlertConfig(min_queries=5, spike_rate=0.4)
        assert should_alert({"total": 10, "weak": 2, "rate": 0.2}, config) is False

    def test_tiny_window_ignored(self):
        config = SpikeAlertConfig(min_queries=5, spike_rate=0.4)
        assert should_alert({"total": 1, "weak": 1, "rate": 1.0}, config) is False


class TestRunSpikeReport:
    def _conn(self, stats_row=None, alert_exists_row=None):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [{"id": 1}]

        def _fetchone():
            # Distinguish the two SELECTs by the SQL passed to execute.
            calls = cur.execute.call_args_list
            last_sql = calls[-1].args[0]
            if "FROM notifications" in last_sql:
                return alert_exists_row or {"n": 0}
            return stats_row or {"total": 0, "weak": 0}

        cur.fetchone.side_effect = _fetchone
        return conn, cur

    def test_below_threshold_no_alert(self):
        conn, cur = self._conn(stats_row={"total": 10, "weak": 2})
        report = run_spike_report(conn)
        assert report["alerted"] is False
        assert report["reason"] == "below_threshold"
        assert not any(
            "INSERT INTO notifications" in c.args[0]
            for c in cur.execute.call_args_list
        )

    def test_above_threshold_notifies_admins(self):
        conn, cur = self._conn(
            stats_row={"total": 10, "weak": 6},
            alert_exists_row={"n": 0},
        )
        report = run_spike_report(conn)
        assert report["alerted"] is True
        assert report["reason"] == "threshold"
        insert_calls = [
            c for c in cur.execute.call_args_list
            if "INSERT INTO notifications" in c.args[0]
        ]
        assert insert_calls, "expected a notification insert"
        args = insert_calls[0].args[1]
        assert DEFAULT_SPIKE_ALERT.alert_type in args

    def test_above_threshold_but_in_cooldown(self):
        conn, cur = self._conn(
            stats_row={"total": 10, "weak": 6},
            alert_exists_row={"n": 1},
        )
        report = run_spike_report(conn)
        assert report["alerted"] is False
        assert report["reason"] == "cooldown"
        assert not any(
            "INSERT INTO notifications" in c.args[0]
            for c in cur.execute.call_args_list
        )

    def test_weak_outcome_rows_are_queried(self):
        conn, cur = self._conn(stats_row={"total": 0, "weak": 0})
        run_spike_report(conn)
        stat_calls = [
            c for c in cur.execute.call_args_list
            if "FROM audit_log" in c.args[0]
        ]
        assert stat_calls, "expected an audit_log aggregate query"
        assert "FILTER (WHERE outcome IN" in stat_calls[0].args[0]
        # window hours param is passed through in the execute args
        assert DEFAULT_SPIKE_ALERT.window_hours in stat_calls[0].args[1]
