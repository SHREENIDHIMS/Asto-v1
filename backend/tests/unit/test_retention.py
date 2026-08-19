"""Phase M5 — retention.py: configured per-table policy, dry-run, audit hook."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from scripts import retention

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


class FakeConn:
    def __init__(self, counts: dict[str, int]):
        self._counts = counts
        self._deleted: dict[str, int] = {}
        self.executed: list[tuple[str, object]] = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.committed = True

    def cursor(self):
        return self._Cursor(self)

    class _Cursor:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self._conn.executed.append((sql, params))
            self._sql = sql
            if sql.startswith("DELETE"):
                table = sql.split("FROM")[1].split("WHERE")[0].strip()
                self._conn._deleted[table] = self._conn._counts.get(table, 0)

        def fetchone(self):
            if "INSERT INTO audit_log" in self._sql:
                return None
            # SELECT count(*) ... -> pick the table name to map to a count
            sql = self._sql
            table = sql.split("FROM")[1].split("WHERE")[0].strip()
            return {"n": self._conn._counts.get(table, 0)}

        @property
        def rowcount(self):
            table = self._sql.split("FROM")[1].split("WHERE")[0].strip()
            return self._conn._counts.get(table, 0)


class TestPolicy:
    def test_policy_covers_regulated_tables(self):
        assert set(retention.RETENTION_POLICY) >= {
            "audit_log",
            "login_attempts",
            "knowledge_gaps",
            "feedback",
            "notifications",
        }

    def test_each_policy_has_date_column_and_days(self):
        for table, (date_col, days) in retention.RETENTION_POLICY.items():
            assert isinstance(date_col, str) and date_col
            assert isinstance(days, int) and days > 0


class TestCutoff:
    def test_cutoff_is_now_minus_days(self):
        assert retention.retention_cutoff(90, NOW) == NOW - timedelta(days=90)


class TestApplyRetention:
    def test_dry_run_counts_without_deleting(self, monkeypatch):
        conn = FakeConn({"audit_log": 5, "login_attempts": 0})
        monkeypatch.setattr(retention, "acquire", lambda: conn)

        result = retention.apply_retention(dry_run=True, now=NOW)
        assert result["audit_log"]["deleted"] == 5
        assert result["login_attempts"]["deleted"] == 0
        assert not conn._deleted
        assert not any(sql.startswith("DELETE") or sql.startswith("INSERT") for sql, _ in conn.executed)

    def test_deletes_rows_older_than_cutoff(self, monkeypatch):
        conn = FakeConn({"audit_log": 5, "knowledge_gaps": 3})
        monkeypatch.setattr(retention, "acquire", lambda: conn)

        result = retention.apply_retention(dry_run=False, now=NOW)
        assert result["audit_log"]["deleted"] == 5
        assert result["knowledge_gaps"]["deleted"] == 3
        deletes = [sql for sql, _ in conn.executed if sql.startswith("DELETE")]
        assert len(deletes) == 2
        assert all("WHERE created_at < %s" in sql for sql in deletes)
        assert conn.committed is True

    def test_audit_logs_the_run_before_deleting(self, monkeypatch):
        conn = FakeConn({"audit_log": 5})
        monkeypatch.setattr(retention, "acquire", lambda: conn)

        retention.apply_retention(dry_run=False, now=NOW)
        insert_idx = next(
            i for i, (sql, _) in enumerate(conn.executed) if sql.startswith("INSERT INTO audit_log")
        )
        delete_idx = next(
            i for i, (sql, _) in enumerate(conn.executed) if sql.startswith("DELETE")
        )
        assert "retention run" in conn.executed[insert_idx][0]
        assert insert_idx < delete_idx


class TestMainCli:
    def test_dry_run_flag_propagates(self, monkeypatch, capsys):
        called = {}

        def spy(dry_run=False, now=None, policy=None):
            called["dry_run"] = dry_run
            return {"audit_log": {"deleted": 0}}

        monkeypatch.setattr(retention, "apply_retention", spy)
        monkeypatch.setattr(sys, "argv", ["retention.py", "--dry-run"])
        assert retention.main() == 0
        assert called["dry_run"] is True
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["audit_log"]["deleted"] == 0

    def test_default_run_is_not_dry(self, monkeypatch):
        called = {}

        def spy(dry_run=False, now=None, policy=None):
            called["dry_run"] = dry_run
            return {}

        monkeypatch.setattr(retention, "apply_retention", spy)
        monkeypatch.setattr(sys, "argv", ["retention.py"])
        retention.main()
        assert called["dry_run"] is False
