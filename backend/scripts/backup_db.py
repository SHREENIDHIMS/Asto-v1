"""M6 — Rotating Postgres backup (one-shot batch).

Takes a custom-format (pg_dump -F c) backup of the Asto database into a
rotating local directory, keeping the newest ``backup_keep`` dumps.

Deliberately a one-shot script (rule 5) — triggered by the
asto-backup.timer on the shared host, or run manually:
    python -m scripts.backup_db

The dump bytes are read from pg_dump stdout so the script works both
when pg_dump is on PATH (host install) and when it must be reached via
a wrapper such as ``docker compose exec -T postgres pg_dump`` (set
ASTO_PGDUMP_COMMAND to that wrapper — stdout is piped back to the host).
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def pg_dump_argv(db_url: str, pg_dump_cmd: str | None) -> list[str]:
    """Build the pg_dump invocation.

    If ``pg_dump_cmd`` is set it is the base command (may be a wrapper
    like ``docker compose exec -T postgres pg_dump``); otherwise plain
    ``pg_dump`` from PATH. The custom format goes to stdout.
    """
    base = shlex.split(pg_dump_cmd) if pg_dump_cmd else ["pg_dump"]
    return [*base, db_url, "-F", "c"]


def prune_backups(backup_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` .dump files; return removed paths."""
    dumps = sorted(backup_dir.glob("*.dump"), key=lambda p: p.name)
    removed: list[Path] = []
    for old in dumps[: max(0, len(dumps) - keep)]:
        old.unlink(missing_ok=True)
        removed.append(old)
    return removed


def run_backup(
    backup_dir: str | Path,
    db_url: str,
    keep: int = 7,
    pg_dump_cmd: str | None = None,
) -> tuple[Path, list[Path]]:
    """Run pg_dump and prune. Returns (outfile, pruned_paths).

    Raises RuntimeError if pg_dump exits non-zero; no partial file is kept.
    """
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outfile = backup_dir / f"asto_{stamp}.dump"

    argv = pg_dump_argv(db_url, pg_dump_cmd)
    result = subprocess.run(argv, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"pg_dump failed (rc={result.returncode}): {stderr}")

    outfile.write_bytes(result.stdout)
    pruned = prune_backups(backup_dir, keep)
    return outfile, pruned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", default=settings.backup_dir)
    parser.add_argument("--keep", type=int, default=settings.backup_keep)
    args = parser.parse_args()

    pg_dump_cmd = os.environ.get("ASTO_PGDUMP_COMMAND")
    try:
        outfile, pruned = run_backup(
            args.backup_dir,
            settings.database_url,
            keep=args.keep,
            pg_dump_cmd=pg_dump_cmd,
        )
    except RuntimeError as exc:
        print(f"BACKUP FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"OK: wrote {outfile} ({outfile.stat().st_size} bytes)")
    for p in pruned:
        print(f"PRUNED: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
