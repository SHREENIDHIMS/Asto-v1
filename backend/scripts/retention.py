"""M5 — Data retention batch job.

Applies the configured retention policy: rows older than N days are
deleted from each listed table (one-shot batch, rule 5). The run is
audit-logged before any deletion so the policy execution itself leaves a
trace, even for tables being pruned.

Run via: python -m scripts.retention [--dry-run]
timer: asto-retention.timer on the shared host.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres.session import acquire  # noqa: E402

#: table -> (date column, retention in days)
RETENTION_POLICY: dict[str, tuple[str, int]] = {
    "audit_log": ("created_at", 730),          # 2y legal/compliance record
    "login_attempts": ("attempted_at", 90),    # brute-force evidence window
    "knowledge_gaps": ("created_at", 365),
    "feedback": ("created_at", 730),
    "notifications": ("created_at", 365),
}


def retention_cutoff(days: int, now: datetime | None = None) -> datetime:
    """Cutoff timestamp: ``now`` minus ``days`` (UTC)."""
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def apply_retention(
    dry_run: bool = False,
    now: datetime | None = None,
    policy: dict[str, tuple[str, int]] | None = None,
) -> dict:
    """Apply the retention policy. Returns {table: {retention_days, deleted}}.

    ``dry_run`` only counts rows that would be deleted (no writes).
    """
    policy = policy or RETENTION_POLICY
    now = now or datetime.now(timezone.utc)
    summary: dict[str, dict] = {}

    with acquire() as conn:
        if not dry_run:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (user_id, query, outcome, created_at) "
                    "VALUES (NULL, 'retention run', %s, now())",
                    (json.dumps({"dry_run": False, "policy": list(policy)}),),
                )

        for table, (date_col, days) in policy.items():
            cutoff = retention_cutoff(days, now)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT count(*) AS n FROM {table} WHERE {date_col} < %s",
                    (cutoff,),
                )
                count = int(cur.fetchone()["n"])
                if not dry_run and count:
                    cur.execute(
                        f"DELETE FROM {table} WHERE {date_col} < %s",
                        (cutoff,),
                    )
                    count = cur.rowcount
            summary[table] = {"retention_days": days, "deleted": count}

        if not dry_run:
            conn.commit()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Asto data retention pass")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count rows that would be deleted without deleting anything",
    )
    args = parser.parse_args()

    result = apply_retention(dry_run=args.dry_run)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())