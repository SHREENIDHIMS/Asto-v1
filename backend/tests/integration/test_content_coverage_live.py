"""Integration test: content coverage SQL runs against a real schema.

Regression guard — the empty_cells query once referenced sops.doc_type,
a column that doesn't exist, and 500'd on every live call while unit
tests (mocked cursors) stayed green.
"""

from __future__ import annotations

from app.documents.coverage import build_coverage_report


def test_coverage_report_runs_on_live_schema():
    from app.db.postgres.session import acquire

    with acquire() as conn:
        report = build_coverage_report(conn)
        assert isinstance(report["coverage"], list)
        assert isinstance(report["empty_cells"], list)

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (title, source_path, doc_type, department) "
                "VALUES ('Covered', 'p/c.pdf', 'policy', 'general') "
                "RETURNING id"
            )
            doc_id = cur.fetchone()["id"]
            cur.execute(
                "UPDATE documents SET approval_status = 'approved', "
                "is_approved = true WHERE id = %s",
                (doc_id,),
            )
        conn.commit()

        try:
            report = build_coverage_report(conn)
            assert any(
                row["department"] == "general" and row["doc_type"] == "policy"
                for row in report["coverage"]
            )
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            conn.commit()
