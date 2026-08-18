"""Integration tests for J5 — spike alerting against a live Postgres.

Seeds a batch of recent audit_log rows (marker-prefixed queries, mixed
outcomes) plus an admin user, then verifies:
  - a weak-rate above threshold creates notification rows for admins
  - the cooldown suppresses a second alert within the window
  - a clean window creates nothing

Skips when the DB is unavailable.
"""

from __future__ import annotations

import pytest

from app.response.spike_alerting import SpikeAlertConfig, run_spike_report


def _db_available() -> bool:
    try:
        from app.db.postgres.session import ping
        return ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Requires a running Postgres instance with asto_assistant schema",
)

_MARKER = "__j5_spike__"
_ALERT_TYPE = "no_answer_spike"


@pytest.fixture(scope="module")
def spike_db():
    """Seed an admin user + audit rows; clean up after the module."""
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                ("j5_admin@example.com", "x", "admin", "general", []),
            )
            admin_id = cur.fetchone()["id"]
            conn.commit()

    yield {"admin_id": admin_id}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM notifications WHERE type = %s",
                (_ALERT_TYPE,),
            )
            cur.execute(
                "DELETE FROM audit_log WHERE query LIKE %s",
                (f"{_MARKER}%",),
            )
            cur.execute(
                "DELETE FROM users WHERE email = %s",
                ("j5_admin@example.com",),
            )
            conn.commit()


def _seed_audit(queries: list[tuple[str, str]]) -> None:
    """Insert audit rows ``(query, outcome)`` now, marker-prefixed."""
    from app.db.postgres.session import acquire

    with acquire() as conn:
        with conn.cursor() as cur:
            for i, (outcome, count) in enumerate(queries):
                for _ in range(count):
                    cur.execute(
                        "INSERT INTO audit_log (user_id, query, outcome, "
                        "confidence, response_id, audience, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, now())",
                        (None, f"{_MARKER}q{i}_{outcome}", outcome, 0.5,
                         f"{_MARKER}resp{i}", "staff"),
                    )
            conn.commit()


def _clear_alerts() -> None:
    """Remove any spike-alert notifications so each test starts clean."""
    from app.db.postgres.session import acquire

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notifications WHERE type = %s", (_ALERT_TYPE,))
            conn.commit()


class TestSpikeAlertingIntegration:
    def _config(self, **overrides):
        base = {
            "window_hours": 24,
            "min_queries": 5,
            "spike_rate": 0.4,
            "cooldown_hours": 0,
            "query_prefix": _MARKER,
        }
        base.update(overrides)
        return SpikeAlertConfig(**base)

    def test_threshold_breach_notifies_admins(self, spike_db):
        _clear_alerts()
        _seed_audit([("answer", 4), ("no_answer", 4), ("partial", 2)])
        config = self._config()

        from app.db.postgres.session import acquire
        with acquire() as conn:
            report = run_spike_report(conn, config)
            conn.commit()

        assert report["alerted"] is True
        assert report["total"] >= 10
        assert report["weak"] >= 6
        assert report["rate"] >= 0.6

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM notifications "
                    "WHERE type = %s AND user_id = %s",
                    (_ALERT_TYPE, spike_db["admin_id"]),
                )
                assert cur.fetchone()["n"] == 1

    def test_clean_window_no_notification(self, spike_db):
        _clear_alerts()
        _seed_audit([("answer", 8)])
        config = self._config()

        from app.db.postgres.session import acquire
        with acquire() as conn:
            report = run_spike_report(conn, config)
            conn.commit()

        assert report["alerted"] is False
        assert report["reason"] == "below_threshold"

    def test_cooldown_suppresses_second_alert(self, spike_db):
        _clear_alerts()
        _seed_audit([("answer", 4), ("no_answer", 4), ("partial", 2)])
        config = self._config(cooldown_hours=72)

        from app.db.postgres.session import acquire
        with acquire() as conn:
            first = run_spike_report(conn, config)
            conn.commit()
            second = run_spike_report(conn, config)
            conn.commit()

        assert first["alerted"] is True
        assert second["alerted"] is False
        assert second["reason"] == "cooldown"

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM notifications "
                    "WHERE type = %s AND user_id = %s",
                    (_ALERT_TYPE, spike_db["admin_id"]),
                )
                assert cur.fetchone()["n"] == 1
