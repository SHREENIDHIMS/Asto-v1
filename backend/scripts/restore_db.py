"""M6 — Restore an Asto database from a custom-format pg_dump (batch).

Companion to scripts/backup_db.py. Restores ``asto_<stamp>.dump`` into the
database named by ASTO_DATABASE_URL (or --db-url).

WARNING: restoring drops/replaces objects in the target database. Point it
at a scratch/empty database for testing, never at the live app DB.

Usage:
    python -m scripts.restore_db path/to/asto_20260818_120000.dump
    python -m scripts.restore_db --db-url postgresql://u:p@host/db path/to/x.dump
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def pg_restore_argv(db_url: str, dump_file: Path, pg_restore_cmd: str | None) -> list[str]:
    base = shlex.split(pg_restore_cmd) if pg_restore_cmd else ["pg_restore"]
    return [*base, "--dbname", db_url, str(dump_file)]


def restore_db(
    dump_file: str | Path,
    db_url: str,
    pg_restore_cmd: str | None = None,
) -> bool:
    """Run pg_restore into db_url. Raises RuntimeError on non-zero exit."""
    dump_file = Path(dump_file)
    if not dump_file.is_file():
        raise FileNotFoundError(f"dump file not found: {dump_file}")

    argv = pg_restore_argv(db_url, dump_file, pg_restore_cmd)
    result = subprocess.run(argv, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"pg_restore failed (rc={result.returncode}): {stderr}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--db-url", default=settings.database_url)
    args = parser.parse_args()

    pg_restore_cmd = os.environ.get("ASTO_PGRESTORE_COMMAND")
    try:
        restore_db(args.dump, args.db_url, pg_restore_cmd=pg_restore_cmd)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"RESTORE FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"OK: restored {args.dump} into {args.db_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
