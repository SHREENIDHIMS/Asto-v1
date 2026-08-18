"""J5 — no-answer / low-confidence spike alerting (one-shot batch).

Run via systemd timer (see shared-host-infra-scaffold/infra/systemd/
asto-report-gaps.timer) — deliberately NOT inside the FastAPI process
(rule 5: heavy/batch work stays out of the API request path).

Aggregates the last 24h of audit_log and, when the weak-outcome rate
crosses the configured threshold, inserts a notification row for admins
(the existing staff notification bell surfaces it).

Usage:
    python -m scripts.report_gaps [--window-hours N] [--spike-rate 0.4]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres import session
from app.response.spike_alerting import (
    DEFAULT_SPIKE_ALERT,
    SpikeAlertConfig,
    run_spike_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-hours", type=int, default=DEFAULT_SPIKE_ALERT.window_hours)
    parser.add_argument("--min-queries", type=int, default=DEFAULT_SPIKE_ALERT.min_queries)
    parser.add_argument("--spike-rate", type=float, default=DEFAULT_SPIKE_ALERT.spike_rate)
    parser.add_argument("--cooldown-hours", type=int, default=DEFAULT_SPIKE_ALERT.cooldown_hours)
    parser.add_argument("--query-prefix", type=str, default=None,
                        help="Only aggregate queries with this prefix (ops/testing)")
    args = parser.parse_args()

    config = SpikeAlertConfig(
        window_hours=args.window_hours,
        min_queries=args.min_queries,
        spike_rate=args.spike_rate,
        cooldown_hours=args.cooldown_hours,
        query_prefix=args.query_prefix,
    )

    with session.acquire() as conn:
        report = run_spike_report(conn, config)
        conn.commit()

    if report["alerted"]:
        print(
            f"ALERT: {report['weak']}/{report['total']} queries weak "
            f"({report['rate']:.0%}) — admins notified"
        )
    else:
        print(
            f"OK: {report['weak']}/{report['total']} queries weak "
            f"({report['rate']:.0%}) — {report.get('reason')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
