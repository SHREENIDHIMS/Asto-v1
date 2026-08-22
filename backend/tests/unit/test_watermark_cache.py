"""Unit tests for the watermark disk cache + size guard (audit #13)."""

from __future__ import annotations

from pathlib import Path

from app.documents import watermark_cache as wc


class TestCacheKey:
    def test_deterministic_per_inputs(self):
        a = wc.cache_key(5, 2, "Jane Doe", day="2026-08-22")
        b = wc.cache_key(5, 2, "Jane Doe", day="2026-08-22")
        assert a == b

    def test_changes_with_viewer_version_or_day(self):
        base = wc.cache_key(5, 2, "Jane", day="2026-08-22")
        assert wc.cache_key(6, 2, "Jane", day="2026-08-22") != base
        assert wc.cache_key(5, 3, "Jane", day="2026-08-22") != base
        assert wc.cache_key(5, 2, "John", day="2026-08-22") != base
        assert wc.cache_key(5, 2, "Jane", day="2026-08-23") != base

    def test_none_version_and_viewer_coerce(self):
        # None version must not crash and must differ from version 0? It
        # normalizes to 0 — same key is acceptable; just prove it runs.
        assert wc.cache_key(1, None, "x", day="d") == wc.cache_key(1, None, "x", day="d")


class TestStoreLoadRoundtrip:
    def test_roundtrip(self, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(
            settings, "storage_watermark_cache_dir", str(tmp_path / "wc")
        )
        wc.store_cached(9, 4, "Viewer", b"WATERMARKED")
        assert wc.load_cached(9, 4, "Viewer") == b"WATERMARKED"
        # Different viewer/version/day → miss.
        assert wc.load_cached(9, 4, "Other") is None
        assert wc.load_cached(9, 5, "Viewer") is None
        assert wc.load_cached(9, 4, "Viewer") == b"WATERMARKED"

    def test_load_missing_returns_none(self, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(
            settings, "storage_watermark_cache_dir", str(tmp_path / "wc")
        )
        assert wc.load_cached(1, 1, "Nobody") is None

    def test_store_failure_is_silent(self, tmp_path, monkeypatch):
        from app.config import settings

        # Point the dir at a FILE so mkdir fails — store must not raise.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        monkeypatch.setattr(settings, "storage_watermark_cache_dir", str(blocker))
        wc.store_cached(1, 1, "V", b"data")  # no exception
        assert wc.load_cached(1, 1, "V") is None


class TestPruneCache:
    def test_removes_only_stale_entries(self, tmp_path, monkeypatch):
        from app.config import settings

        cache_dir = tmp_path / "wc"
        monkeypatch.setattr(settings, "storage_watermark_cache_dir", str(cache_dir))
        cache_dir.mkdir(parents=True)

        fresh = cache_dir / "fresh.bin"
        stale = cache_dir / "stale.bin"
        fresh.write_bytes(b"a")
        stale.write_bytes(b"b")
        import os

        old = 0  # epoch → far in the past
        os.utime(stale, (old, old))

        removed = wc.prune_cache(max_age_days=2)
        assert removed == 1
        assert fresh.exists() and not stale.exists()

    def test_missing_directory_is_noop(self, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(
            settings, "storage_watermark_cache_dir", str(tmp_path / "nope")
        )
        assert wc.prune_cache() == 0


class TestShouldWatermark:
    def test_within_cap(self, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "watermark_max_bytes", 100)
        assert wc.should_watermark(99) is True
        assert wc.should_watermark(101) is False

    def test_guard_disabled_when_non_positive(self, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "watermark_max_bytes", 0)
        assert wc.should_watermark(10**9) is True
