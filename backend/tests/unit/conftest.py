"""Shared fixtures and mocks for unit tests.

These tests must run without a live Postgres instance. We mock the
``acquire`` context manager in the session module so endpoints that
call ``acquire()`` get a fake connection returning no rows.

The patch is applied via an autouse fixture (not at import time) so it
never leaks into integration tests that share the same pytest session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


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
