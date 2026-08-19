"""Unit tests for Phase M6 backup/restore scripts.

Covers: pg_dump argv construction (plain + wrapper command), successful
backup writes a dump and prunes old ones, pg_dump failure raises and
keeps no partial file, prune keep-N logic, and pg_restore invocation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.backup_db import pg_dump_argv, prune_backups, run_backup
from scripts.restore_db import restore_db


class TestPgDumpArgv:
    def test_plain_pg_dump(self):
        argv = pg_dump_argv("postgresql://u:p@h/db", None)
        assert argv[:1] == ["pg_dump"]
        assert "postgresql://u:p@h/db" in argv
        assert "-F" in argv and "c" in argv

    def test_wrapper_command(self):
        argv = pg_dump_argv("postgresql://u:p@h/db", "docker compose exec -T postgres pg_dump")
        assert argv[:6] == ["docker", "compose", "exec", "-T", "postgres", "pg_dump"]


class TestPrune:
    def test_keeps_newest_n(self, tmp_path: Path):
        for i in range(5):
            (tmp_path / f"asto_2026010{i+1}_000000.dump").write_bytes(b"x")
        removed = prune_backups(tmp_path, keep=2)
        remaining = sorted(p.name for p in tmp_path.glob("*.dump"))
        assert len(removed) == 3
        assert remaining == ["asto_20260104_000000.dump", "asto_20260105_000000.dump"]

    def test_no_prune_when_under_limit(self, tmp_path: Path):
        (tmp_path / "asto_a.dump").write_bytes(b"x")
        removed = prune_backups(tmp_path, keep=7)
        assert removed == []


class TestRunBackup:
    def test_success_writes_dump_and_prunes(self, tmp_path: Path):
        (tmp_path / "asto_20260101_000000.dump").write_bytes(b"old")
        ok = subprocess.CompletedProcess([], 0, stdout=b"PGDUMPDATA", stderr=b"")
        with patch("scripts.backup_db.subprocess.run", return_value=ok) as run:
            outfile, pruned = run_backup(
                tmp_path, "postgresql://u:p@h/db", keep=1
            )

        run.assert_called_once()
        argv = run.call_args.args[0]
        assert "postgresql://u:p@h/db" in argv and "-F" in argv
        assert outfile.read_bytes() == b"PGDUMPDATA"
        assert outfile.name.startswith("asto_")
        assert len(pruned) == 1  # old dump pruned

    def test_failure_raises_and_keeps_no_file(self, tmp_path: Path):
        bad = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"boom")
        with patch("scripts.backup_db.subprocess.run", return_value=bad):
            try:
                run_backup(tmp_path, "postgresql://u:p@h/db", keep=1)
                raised = False
            except RuntimeError as exc:
                raised = True
                assert "boom" in str(exc)
        assert raised
        assert list(tmp_path.glob("*.dump")) == []


class TestRestore:
    def test_restore_invokes_pg_restore(self, tmp_path: Path):
        dump = tmp_path / "asto_x.dump"
        dump.write_bytes(b"d")
        ok = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
        with patch("scripts.restore_db.subprocess.run", return_value=ok) as run:
            assert restore_db(dump, "postgresql://u:p@h/db") is True
        argv = run.call_args.args[0]
        assert argv[0] == "pg_restore"
        assert "postgresql://u:p@h/db" in argv
        assert str(dump) in argv

    def test_restore_missing_file(self, tmp_path: Path):
        try:
            restore_db(tmp_path / "nope.dump", "postgresql://u:p@h/db")
            raised = False
        except FileNotFoundError:
            raised = True
        assert raised
