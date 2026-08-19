"""M8 — feature flags.

Ship half-built features safely: every risky new endpoint is gated behind a
named flag. Flags live in the ``feature_flags`` Postgres table (single source
of truth); ``DEFAULT_FLAGS`` below fills gaps so an un-seeded flag still has a
documented, predictable value on a fresh database.

The table is checked with a short TTL cache (15s) so request-path reads stay
cheap and a toggle takes effect almost immediately.
"""

from __future__ import annotations

import threading
import time

from app.db.postgres import session

#: Config-level defaults. DB rows override these; the row wins.
DEFAULT_FLAGS: dict[str, bool] = {
    # M1 audit-log export is a data-exfiltration surface — gate it.
    "audit_export": True,
}

_CACHE_TTL_SECONDS = 15.0
_cache: dict[str, bool] = {}
_cache_loaded_at = 0.0
_lock = threading.Lock()


def is_enabled(name: str) -> bool:
    """Return whether the named feature flag is currently on.

    Falls back to ``DEFAULT_FLAGS`` when the DB is unreachable or the row is
    missing — the table only ever overrides the compiled-in default.
    """
    value = _load_flag(name)
    if value is not None:
        return value
    return DEFAULT_FLAGS.get(name, False)


def _load_flag(name: str) -> bool | None:
    """Read a flag from the cached snapshot, or None if unknown/unavailable."""
    now = time.monotonic()
    with _lock:
        if now - _cache_loaded_at > _CACHE_TTL_SECONDS:
            _refresh_cache_unlocked()
        return _cache.get(name)


def _refresh_cache_unlocked() -> None:
    """Rebuild the in-memory snapshot of all rows (caller holds the lock)."""
    global _cache_loaded_at
    _cache_loaded_at = time.monotonic()
    try:
        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name, enabled FROM feature_flags")
                _cache.clear()
                for row in cur.fetchall():
                    _cache[str(row["name"])] = bool(row["enabled"])
    except Exception:  # noqa: BLE001 - degrade to defaults on DB failure
        _cache.clear()


def get_all_flags() -> list[dict]:
    """Return every known flag with its effective value and source."""
    names = sorted(set(DEFAULT_FLAGS) | set(_load_all_names()))
    rows: list[dict] = []
    for name in names:
        rows.append(
            {
                "name": name,
                "enabled": is_enabled(name),
                "source": "table" if name in _load_all_names() else "default",
            }
        )
    return rows


def _load_all_names() -> set[str]:
    try:
        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM feature_flags")
                return {str(r["name"]) for r in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return set()


def set_flag(name: str, enabled: bool, updated_by: int | None = None) -> dict:
    """Upsert a flag and refresh the cache so the change is immediate."""
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_flags (name, enabled, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (name) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    updated_at = now()
                """,
                (name, enabled),
            )
    with _lock:
        _refresh_cache_unlocked()
    return {"name": name, "enabled": enabled}
