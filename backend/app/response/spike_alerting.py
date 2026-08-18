"""No-answer / low-confidence spike alerting (J5).

Aggregates the last N hours of ``audit_log`` rows and flags when the
share of ``no_answer``/``partial`` outcomes crosses a configured rate.

This module is configuration + pure logic (rule 7: thresholds are
configuration, not constants). It is invoked by the one-shot batch
script ``scripts/report_gaps.py`` (systemd timer) — never from inside a
request handler (rule 5: heavy/batch work stays out of the API process).

The notification insert uses the generic ``notifications`` inbox so the
alert shows up in the existing staff bell UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WEAK_OUTCOMES = frozenset({"no_answer", "partial"})


@dataclass
class SpikeAlertConfig:
    """Thresholds for the spike alert. Change based on ops evidence,
    not a "better-feeling" number (rule 7)."""

    window_hours: int = 24      # how far back to aggregate audit rows
    min_queries: int = 5        # ignore tiny windows (avoid noise)
    spike_rate: float = 0.40    # fraction of weak outcomes that triggers
    cooldown_hours: int = 24    # don't re-alert within this window
    alert_type: str = "no_answer_spike"
    alert_title: str = "Search quality spike detected"
    alert_link: str | None = "/admin/analytics"
    query_prefix: str | None = None  # restrict to a query prefix (tests)


DEFAULT_SPIKE_ALERT = SpikeAlertConfig()


def compute_window_stats(outcomes: list[str]) -> dict:
    """Aggregate outcome strings into window statistics.

    Pure helper (no DB) so the threshold logic is unit-testable:
    returns ``{"total": n, "weak": n_weak, "rate": weak/total}`` where
    ``weak`` counts the ``WEAK_OUTCOMES`` (``no_answer``, ``partial``).
    """
    total = len(outcomes)
    weak = sum(1 for o in outcomes if o in WEAK_OUTCOMES)
    return {
        "total": total,
        "weak": weak,
        "rate": (weak / total) if total else 0.0,
    }


def should_alert(stats: dict, config: SpikeAlertConfig) -> bool:
    """True when a window crosses the configured spike threshold."""
    return (
        stats["total"] >= config.min_queries
        and stats["rate"] >= config.spike_rate
    )


def _weak_outcome_placeholder() -> str:
    """SQL-safe comma-joined placeholder list for the weak-outcome set."""
    return ", ".join(["%s"] * len(WEAK_OUTCOMES))


def load_window_stats(conn, config: SpikeAlertConfig) -> dict:
    """Aggregate the window: total queries vs weak outcomes from audit_log.

    ``total`` counts every routed query in the window (outcome present);
    ``weak`` counts the ``WEAK_OUTCOMES`` subset. Returns a
    ``compute_window_stats``-shaped dict so callers share one shape.
    When ``query_prefix`` is set, only marker-prefixed queries are counted
    (used by tests to isolate against other seeded rows).
    """
    weak_placeholders = _weak_outcome_placeholder()
    prefix_filter = " AND query LIKE %s" if config.query_prefix else ""
    prefix_params = (f"{config.query_prefix}%",) if config.query_prefix else ()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COUNT(*) FILTER (WHERE outcome IN (" + weak_placeholders + ")) AS weak "
            "FROM audit_log "
            "WHERE created_at >= now() - make_interval(hours => %s) "
            "AND outcome IS NOT NULL"
            + prefix_filter,
            (*sorted(WEAK_OUTCOMES), config.window_hours, *prefix_params),
        )
        row = cur.fetchone()
    total = int(row["total"] or 0)
    weak = int(row["weak"] or 0)
    return {
        "total": total,
        "weak": weak,
        "rate": (weak / total) if total else 0.0,
    }


def _recent_alert_exists(conn, config: SpikeAlertConfig) -> bool:
    """True when a spike alert was already raised inside the cooldown."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM notifications "
            "WHERE type = %s "
            "AND created_at >= now() - make_interval(hours => %s)",
            (config.alert_type, config.cooldown_hours),
        )
        return int(cur.fetchone()["n"] or 0) > 0


def _notify_admins(conn, config: SpikeAlertConfig, stats: dict) -> None:
    """Insert a notification for every admin user (no commit — caller commits)."""
    from app.api.v1.notifications import notify_admins

    body = (
        f"{stats['weak']} of the last {stats['total']} queries in the past "
        f"{config.window_hours}h returned no answer or a partial answer "
        f"({stats['rate']:.0%}). Check retrieval health."
    )
    notify_admins(conn, config.alert_type, config.alert_title, body, config.alert_link)


def run_spike_report(conn, config: SpikeAlertConfig | None = None) -> dict:
    """Full J5 batch: aggregate the window, alert on breach.

    Called by ``scripts/report_gaps.py``. Returns a report dict so the
    script can log what happened. Does NOT commit — the caller commits so
    the notification insert is atomic with the read.
    """
    config = config or DEFAULT_SPIKE_ALERT
    stats = load_window_stats(conn, config)

    result = {**stats, "alerted": False}
    if should_alert(stats, config):
        if _recent_alert_exists(conn, config):
            result["reason"] = "cooldown"
        else:
            _notify_admins(conn, config, stats)
            result["alerted"] = True
            result["reason"] = "threshold"
    else:
        result["reason"] = "below_threshold"
    return result
