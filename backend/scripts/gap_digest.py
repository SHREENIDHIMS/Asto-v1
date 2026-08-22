"""Weekly knowledge-gap digest (one-shot batch).

Run via systemd timer (pair with the existing asto-report-gaps pattern in
shared-host-infra-scaffold/infra/systemd/) — deliberately NOT inside the
FastAPI process (rule 5). Aggregates the last N days of knowledge_gaps +
weak outcomes and emails a digest to every active admin.

Usage:
    python -m scripts.gap_digest [--window-days 7] [--top-n 10]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres import session
from app.knowledge_gap.digest import (
    DEFAULT_DIGEST,
    GapDigestConfig,
    collect_digest,
    email_digest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-days", type=int, default=DEFAULT_DIGEST.window_days)
    parser.add_argument("--top-n", type=int, default=DEFAULT_DIGEST.top_n)
    args = parser.parse_args()

    config = GapDigestConfig(window_days=args.window_days, top_n=args.top_n)

    with session.acquire() as conn:
        report = collect_digest(conn, config)
        emailed = email_digest(conn, report)

    print(
        f"Digest: {report['total_gaps']} gaps "
        f"({report['distinct_queries']} distinct) over {report['window_days']}d; "
        f"weak outcomes {report['weak']['count']}/{report['weak']['total']} "
        f"({report['weak']['rate']:.0%}); emailed to {emailed} admin(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
