"""Shared fixtures and mocks for unit tests.

These tests must run without a live Postgres instance. We mock the
``acquire`` context manager in the session module so endpoints that
call ``acquire()`` get a fake connection returning no rows.

The patch is applied via an autouse fixture (not at import time) so it
never leaks into integration tests that share the same pytest session.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _fake_conn() -> MagicMock:
    """Return a connection whose cursor.fetchall returns no rows."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


@pytest.fixture(autouse=True)
def _mock_db_acquire():
    """Patch acquire for every unit test, restoring it afterwards."""
    patcher = patch("app.db.postgres.session.acquire", return_value=_fake_conn())
    patcher.start()
    yield
    patcher.stop()


@pytest.fixture(autouse=True)
def _isolated_watermark_cache(tmp_path, monkeypatch):
    """Point the watermark disk cache at a per-test temp directory so
    endpoint tests never write into the real storage/ tree."""
    from app.config import settings

    monkeypatch.setattr(
        settings,
        "storage_watermark_cache_dir",
        str(tmp_path / "watermark_cache"),
    )
