"""Root test configuration.

Gates which database the test suite connects to. Integration tests are
potentially destructive — they seed and clear benchmark corpus rows — so
they must never run against a developer's real database by accident.

If ``ASTO_TEST_DATABASE_URL`` is set, every test in this session uses that
database instead of ``ASTO_DATABASE_URL`` / the config default. This runs
at conftest import time (before any ``app.config`` import), so the cached
``settings`` object picks up the gated URL.
"""

from __future__ import annotations

import os


def _gate_test_database() -> None:
    test_db_url = os.environ.get("ASTO_TEST_DATABASE_URL")
    if test_db_url:
        os.environ["ASTO_DATABASE_URL"] = test_db_url


_gate_test_database()
