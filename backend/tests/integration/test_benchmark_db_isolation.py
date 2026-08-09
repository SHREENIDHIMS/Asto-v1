"""Verify benchmark seed/clear is scoped to its own rows.

Regression guard for the design decision 2026-08-09: `clear_benchmark_data()`
must only delete rows created by `seed_benchmark_data()` (marked via
`source_path = '__benchmark_seed__'`). Previously it deleted ALL documents,
which could wipe unrelated dev/production data when tests ran against a
developer's real database.

Requires a live Postgres instance; skips gracefully otherwise.
"""

from __future__ import annotations

import pytest

from app.db.postgres.session import ping
from evaluation.datasets.seed_benchmark_data import (
    BENCHMARK_SOURCE,
    clear_benchmark_data,
    seed_benchmark_data,
)


pytestmark = pytest.mark.skipif(
    not ping(),
    reason="Requires a running Postgres instance with asto_assistant schema",
)


@pytest.fixture()
def unrelated_doc_id():
    """Insert a document that is NOT part of the benchmark seed."""
    from app.db.postgres.session import acquire

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (title, doc_type, department, is_active, is_approved, version, source_path) "
                "VALUES (%s, %s, %s, true, true, 1, %s) RETURNING id",
                ("Unrelated Dev Fixture", "policy", "general", "/dev/fixture.pdf"),
            )
            doc_id = cur.fetchone()["id"]
            conn.commit()
    yield doc_id
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            conn.commit()


def _doc_exists(doc_id: int) -> bool:
    from app.db.postgres.session import acquire

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM documents WHERE id = %s", (doc_id,))
            return cur.fetchone() is not None


class TestClearScopedToBenchmarkRows:
    def test_clear_removes_only_benchmark_seeded_rows(self, unrelated_doc_id):
        clear_benchmark_data()

        topics = seed_benchmark_data()
        assert len(topics) > 0

        # Benchmark rows exist after seeding
        from app.db.postgres.session import acquire

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM documents WHERE source_path = %s",
                    (BENCHMARK_SOURCE,),
                )
                seeded = cur.fetchone()["n"]
        assert seeded > 0

        # A second clear removes the seeded rows...
        clear_benchmark_data()
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM documents WHERE source_path = %s",
                    (BENCHMARK_SOURCE,),
                )
                remaining = cur.fetchone()["n"]
        assert remaining == 0

        # ...but the unrelated fixture survives untouched
        assert _doc_exists(unrelated_doc_id), "clear_benchmark_data wiped unrelated data"

    def test_seed_and_clear_are_idempotent_without_wiping_others(self, unrelated_doc_id):
        clear_benchmark_data()
        seed_benchmark_data()

        # Re-running seed against an already-seeded corpus must not break
        # (clear first, then seed — the pattern every benchmark caller uses).
        clear_benchmark_data()
        topics = seed_benchmark_data()
        assert len(topics) > 0
        assert _doc_exists(unrelated_doc_id)
