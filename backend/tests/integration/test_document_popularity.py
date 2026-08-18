"""Integration tests for J6 — document popularity analytics (real DB).

Seeds a known document + marker-prefixed audit_log rows (answer/partial/
no_answer) + a feedback row, then verifies the aggregation counts,
positive ratio, and underperforming detection computed by a live SQL
query. Skips when the DB is unavailable.
"""

from __future__ import annotations

import pytest

from app.response.spike_alerting import SpikeAlertConfig


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

_MARKER = "__j6_poptest__"
_DOC_TITLE = "J6 Popularity Test Doc"
_ALERT_TYPE = "no_answer_spike"


def _find_or_create_doc(conn):
    """Return a document id for the test (create if absent)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM documents WHERE title = %s LIMIT 1", (_DOC_TITLE,)
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO documents (title, doc_type, department, client_id, "
            "property_id, approval_status) "
            "VALUES (%s, 'policy', 'general', NULL, NULL, 'approved') RETURNING id",
            (_DOC_TITLE,),
        )
        conn.commit()
        return cur.fetchone()["id"]


@pytest.fixture
def pop_doc():
    """Seed a document + audit rows + one feedback row; clean up after."""
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema

    ensure_schema()
    resp_id = f"{_MARKER}resp"

    with acquire() as conn:
        doc_id = _find_or_create_doc(conn)
        with conn.cursor() as cur:
            # 1 answer + 3 partial = 4 answered outcomes, plus 1 feedback (+1)
            cur.execute(
                "INSERT INTO audit_log (user_id, query, outcome, confidence, "
                "response_id, audience, retrieved_ids, created_at) "
                "VALUES (%s, %s, 'answer', 0.95, %s, 'staff', %s, now())",
                (1, f"{_MARKER}answer", resp_id, [doc_id]),
            )
            for i in range(3):
                cur.execute(
                    "INSERT INTO audit_log (user_id, query, outcome, confidence, "
                    "response_id, audience, retrieved_ids, created_at) "
                    "VALUES (%s, %s, 'partial', 0.7, %s, 'staff', %s, now())",
                    (1, f"{_MARKER}partial{i}", resp_id, [doc_id]),
                )
            for i in range(2):
                cur.execute(
                    "INSERT INTO audit_log (user_id, query, outcome, confidence, "
                    "response_id, audience, retrieved_ids, created_at) "
                    "VALUES (%s, %s, 'no_answer', 0.1, %s, 'staff', %s, now())",
                    (1, f"{_MARKER}noanswer{i}", None, [doc_id]),
                )
            cur.execute(
                "INSERT INTO feedback (response_id, user_id, rating, comment) "
                "VALUES (%s, %s, 1, 'good')",
                (resp_id, 1),
            )
            conn.commit()

    yield doc_id

    from app.db.postgres.session import acquire
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audit_log WHERE query LIKE %s", (f"{_MARKER}%",))
            cur.execute("DELETE FROM feedback WHERE response_id = %s", (resp_id,))
            cur.execute("DELETE FROM documents WHERE title = %s", (_DOC_TITLE,))
            conn.commit()


class TestDocumentPopularityIntegration:
    def test_aggregation_counts(self, pop_doc):
        from app.db.postgres.session import acquire
        from app.api.v1.analytics import _rank_popularity, _document_popularity_rows

        with acquire() as conn:
            rows = _document_popularity_rows(conn, limit=20)

        doc = next((r for r in rows if r["doc_id"] == pop_doc), None)
        assert doc is not None, "test doc not in results"
        assert int(doc["answer_count"]) == 4  # 1 answer + 3 partial
        assert int(doc["no_answer_count"]) == 2
        assert int(doc["distinct_users"]) == 1
        assert int(doc["positive_count"]) == 1
        assert int(doc["negative_count"]) == 0

        ranked = _rank_popularity(rows)
        entry = next(d for d in ranked["top_documents"] if d["doc_id"] == pop_doc)
        assert entry["positive_ratio"] == 1.0
        # 4 answers, 1 positive review, 0 negative -> not underperforming
        assert not any(
            d["doc_id"] == pop_doc for d in ranked["underperforming_documents"]
        )

    def test_underperforming_with_negative_review(self, pop_doc):
        from app.db.postgres.session import acquire
        from app.api.v1.analytics import _rank_popularity, _document_popularity_rows

        # Add two negative reviews on the same answered response (1 positive,
        # 2 negative -> ratio 1/3 < 0.5 with a negative present -> underperforming).
        resp_id = f"{_MARKER}resp"
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO feedback (response_id, user_id, rating, comment) "
                    "VALUES (%s, %s, -1, 'wrong')",
                    (resp_id, 1),
                )
                cur.execute(
                    "INSERT INTO feedback (response_id, user_id, rating, comment) "
                    "VALUES (%s, %s, -1, 'still wrong')",
                    (resp_id, 2),
                )
                conn.commit()
            rows = _document_popularity_rows(conn, limit=20)

        doc = next((r for r in rows if r["doc_id"] == pop_doc), None)
        assert int(doc["positive_count"]) == 1
        assert int(doc["negative_count"]) == 2
        ranked = _rank_popularity(rows)
        under = next(
            (d for d in ranked["underperforming_documents"] if d["doc_id"] == pop_doc),
            None,
        )
        assert under is not None, "doc with negative reviews should be underperforming"
