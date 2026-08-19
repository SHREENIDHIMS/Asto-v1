"""M3 — Scheduled pgvector/index maintenance (one-shot batch).

Keeps hybrid search fast as the corpus grows:

1. ``VACUUM (ANALYZE) documents, document_chunks`` — reclaim dead tuples
   and refresh planner statistics.
2. When dead-tuple bloat on ``document_chunks`` exceeds a threshold,
   ``REINDEX INDEX CONCURRENTLY`` the pgvector HNSW index
   (``idx_chunks_embedding``) and the FTS GIN index (``idx_chunks_fts``).
   CONCURRENTLY keeps the table available for reads/writes during rebuild.
3. The ``fts`` column is ``GENERATED ALWAYS ... STORED``, so "refreshing
   FTS" is exactly the ANALYZE in step 1 (keeps GIN stats current).

Deliberately a one-shot script (CLAUDE.md rule 5) — triggered by the
asto-maintenance.timer on the shared host, or run manually:

    python -m scripts.maintenance [--dry-run] [--reindex-threshold 0.2]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres.session import acquire  # noqa: E402

VACUUM_TABLES = ("documents", "document_chunks")
REINDEX_TARGETS = ("idx_chunks_embedding", "idx_chunks_fts")
DEFAULT_REINDEX_THRESHOLD = 0.2


def bloat_ratio(conn) -> float:
    """Dead-tuple ratio for document_chunks (0.0 when the stats row is absent)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables "
            "WHERE relname = 'document_chunks'"
        )
        row = cur.fetchone()
    if not row:
        return 0.0
    live = int(row["n_live_tup"] or 0)
    dead = int(row["n_dead_tup"] or 0)
    total = live + dead
    return dead / total if total > 0 else 0.0


def vacuum_analyze(conn) -> None:
    """VACUUM ANALYZE the search tables (requires autocommit)."""
    for table in VACUUM_TABLES:
        with conn.cursor() as cur:
            cur.execute(f"VACUUM (ANALYZE) {table}")


def reindex_index(conn, index_name: str) -> None:
    """REINDEX INDEX CONCURRENTLY one index (requires autocommit)."""
    with conn.cursor() as cur:
        cur.execute(f"REINDEX INDEX CONCURRENTLY {index_name}")


def run_maintenance(
    reindex_threshold: float = DEFAULT_REINDEX_THRESHOLD,
    dry_run: bool = False,
) -> dict:
    """Run the maintenance pass. Returns a JSON-serializable summary.

    ``dry_run`` reports the bloat ratio without executing VACUUM/REINDEX.
    """
    with acquire() as conn:
        conn.autocommit = True
        ratio = bloat_ratio(conn)
        result: dict = {
            "bloat_ratio": round(ratio, 4),
            "vacuumed": False,
            "reindexed": False,
            "reindexed_indexes": [],
        }
        if dry_run:
            return result

        vacuum_analyze(conn)
        result["vacuumed"] = True

        if ratio > reindex_threshold:
            for index_name in REINDEX_TARGETS:
                reindex_index(conn, index_name)
                result["reindexed_indexes"].append(index_name)
            result["reindexed"] = True

        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Asto DB maintenance pass")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report bloat without executing VACUUM/REINDEX",
    )
    parser.add_argument(
        "--reindex-threshold",
        type=float,
        default=DEFAULT_REINDEX_THRESHOLD,
        help="dead-tuple ratio above which HNSW/GIN indexes are rebuilt",
    )
    args = parser.parse_args()

    result = run_maintenance(
        reindex_threshold=args.reindex_threshold, dry_run=args.dry_run
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())