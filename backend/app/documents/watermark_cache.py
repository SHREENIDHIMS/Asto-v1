"""Disk cache + size guard for request-time watermarking (audit #13).

Watermark text is viewer- and date-specific, so it can never be
precomputed at ingestion — pypdf/PIL necessarily run inside the serving
process. Hardening therefore targets the two real risks:

1. **Unbounded work**: files above ``settings.watermark_max_bytes`` skip
   watermarking entirely (served as an audited attachment by the caller)
   instead of risking the worker's memory cap on a huge PDF.
2. **Repeated reprocessing**: watermarked bytes are cached on disk keyed
   by ``(document_id, version, viewer, day)`` — the same key that
   determines the stamp itself — so a client viewing the same document
   again the same day costs one file read, not another pypdf pass.

Cache entries naturally expire when the date rolls over; ``prune_cache``
(called from the maintenance batch) removes stale files so the directory
doesn't grow forever.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    return Path(settings.storage_watermark_cache_dir)


def cache_key(document_id: int, version: int | None, viewer: str,
              day: str | None = None) -> str:
    """Deterministic cache key; ``day`` defaults to today (UTC)."""
    if day is None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
    raw = f"{document_id}:{version or 0}:{viewer}:{day}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def cached_path(key: str) -> Path:
    return _cache_dir() / f"{key}.bin"


def load_cached(document_id: int, version: int | None, viewer: str) -> bytes | None:
    """Return the cached watermarked bytes for today, or None."""
    path = cached_path(cache_key(document_id, version, viewer))
    try:
        return path.read_bytes()
    except OSError:
        return None


def store_cached(document_id: int, version: int | None, viewer: str,
                 data: bytes) -> None:
    """Persist watermarked bytes for reuse today. Best-effort: a cache
    write failure must never break document delivery."""
    try:
        directory = _cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        tmp = cached_path(cache_key(document_id, version, viewer)).with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(cached_path(cache_key(document_id, version, viewer)))
    except OSError:
        logger.warning("watermark cache write failed", exc_info=True)


def prune_cache(max_age_days: int = 2) -> int:
    """Delete cache entries older than ``max_age_days``. Returns removed count.

    Entries are keyed by day, so anything older than yesterday can never be
    hit again. Called from the maintenance batch, never from a request path.
    """
    cutoff = (datetime.now(UTC)).timestamp() - max_age_days * 86400
    removed = 0
    directory = _cache_dir()
    if not directory.exists():
        return 0
    for path in directory.glob("*.bin"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def should_watermark(size_bytes: int) -> bool:
    """True when watermarking should be attempted for a file of this size.

    A non-positive ``watermark_max_bytes`` disables the guard (always
    attempt); otherwise files above the cap skip watermarking.
    """
    cap = settings.watermark_max_bytes
    if cap <= 0:
        return True
    return size_bytes <= cap
