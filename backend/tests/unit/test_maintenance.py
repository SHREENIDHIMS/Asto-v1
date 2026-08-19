"""Phase M3 — maintenance.py: VACUUM ANALYZE, bloat-gated REINDEX, dry-run."""

from __future__ import annotations

import json
import sys

import pytest

from scripts import maintenance


class FakeConn:
    def __init__(self, stats_row=None):
        self.autocommit = False
        self._stats_row = stats_row
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

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
            self._conn.executed.append(sql)
            self._sql = sql

        def fetchone(self):
            if "pg_stat_user_tables" in self._sql:
                return self._conn._stats_row
            return None


def _patch_acquire(monkeypatch, conn):
    monkeypatch.setattr(maintenance, "acquire", lambda: conn)
    return conn


class TestBloatRatio:
    def test_missing_stats_row_returns_zero(self, monkeypatch):
        conn = _patch_acquire(monkeypatch, FakeConn(stats_row=None))
        assert maintenance.bloat_ratio(conn) == 0.0

    def test_computes_dead_ratio(self, monkeypatch):
        conn = _patch_acquire(monkeypatch, FakeConn(stats_row={"n_live_tup": 80, "n_dead_tup": 20}))
        assert maintenance.bloat_ratio(conn) == pytest.approx(0.2)

    def test_zero_live_guard(self, monkeypatch):
        conn = _patch_acquire(monkeypatch, FakeConn(stats_row={"n_live_tup": 0, "n_dead_tup": 0}))
        assert maintenance.bloat_ratio(conn) == 0.0


class TestRunMaintenance:
    def test_dry_run_reports_without_actions(self, monkeypatch):
        conn = _patch_acquire(
            monkeypatch,
            FakeConn(stats_row={"n_live_tup": 50, "n_dead_tup": 50}),
        )
        result = maintenance.run_maintenance(dry_run=True)
        assert result["bloat_ratio"] == pytest.approx(0.5)
        assert result["vacuumed"] is False
        assert result["reindexed"] is False
        assert not any(sql.startswith("VACUUM") or sql.startswith("REINDEX") for sql in conn.executed)

    def test_enables_autocommit(self, monkeypatch):
        conn = _patch_acquire(monkeypatch, FakeConn(stats_row=None))
        maintenance.run_maintenance(dry_run=True)
        assert conn.autocommit is True

    def test_low_bloat_vacuums_but_does_not_reindex(self, monkeypatch):
        conn = _patch_acquire(
            monkeypatch,
            FakeConn(stats_row={"n_live_tup": 90, "n_dead_tup": 10}),
        )
        result = maintenance.run_maintenance(reindex_threshold=0.5)
        assert result["vacuumed"] is True
        assert result["reindexed"] is False
        vacuums = [sql for sql in conn.executed if sql.startswith("VACUUM")]
        assert len(vacuums) == 2
        assert all("documents" in sql or "document_chunks" in sql for sql in vacuums)
        assert not any(sql.startswith("REINDEX") for sql in conn.executed)

    def test_high_bloat_reindexes_both_indexes(self, monkeypatch):
        conn = _patch_acquire(
            monkeypatch,
            FakeConn(stats_row={"n_live_tup": 50, "n_dead_tup": 50}),
        )
        result = maintenance.run_maintenance(reindex_threshold=0.2)
        assert result["reindexed"] is True
        assert result["reindexed_indexes"] == ["idx_chunks_embedding", "idx_chunks_fts"]
        reindexes = [sql for sql in conn.executed if sql.startswith("REINDEX")]
        assert len(reindexes) == 2
        assert all("CONCURRENTLY" in sql for sql in reindexes)
        vacuums = [sql for sql in conn.executed if sql.startswith("VACUUM")]
        assert len(vacuums) == 2


class TestMainCli:
    def test_dry_run_flag_propagates(self, monkeypatch, capsys):
        called = {}

        def spy(reindex_threshold=maintenance.DEFAULT_REINDEX_THRESHOLD, dry_run=False):
            called["threshold"] = reindex_threshold
            called["dry_run"] = dry_run
            return {"bloat_ratio": 0.0, "vacuumed": False, "reindexed": False}

        monkeypatch.setattr(maintenance, "run_maintenance", spy)
        monkeypatch.setattr(sys, "argv", ["maintenance.py", "--dry-run"])
        assert maintenance.main() == 0
        assert called == {"threshold": 0.2, "dry_run": True}

    def test_threshold_flag_propagates(self, monkeypatch):
        called = {}

        def spy(reindex_threshold=maintenance.DEFAULT_REINDEX_THRESHOLD, dry_run=False):
            called["threshold"] = reindex_threshold
            return {"bloat_ratio": 0.0}

        monkeypatch.setattr(maintenance, "run_maintenance", spy)
        monkeypatch.setattr(
            sys, "argv", ["maintenance.py", "--reindex-threshold", "0.5"]
        )
        maintenance.main()
        assert called["threshold"] == 0.5

    def test_prints_json_summary(self, monkeypatch, capsys):
        conn = _patch_acquire(
            monkeypatch,
            FakeConn(stats_row={"n_live_tup": 90, "n_dead_tup": 10}),
        )
        monkeypatch.setattr(
            sys, "argv", ["maintenance.py", "--reindex-threshold", "0.5"]
        )
        assert maintenance.main() == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["vacuumed"] is True
        assert payload["reindexed"] is False