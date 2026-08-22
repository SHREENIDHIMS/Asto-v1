"""Unit tests for the content coverage report (thin-KB analytics)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.documents.coverage import (
    build_coverage_report,
    coverage_by_department,
    empty_cells,
)


def _conn(fetchall_queue: list[list[dict]]) -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    batches = iter(fetchall_queue)
    cur.fetchall.side_effect = lambda: next(batches, [])
    return conn


class TestCoverageByDepartment:
    def test_counts_cast_and_thinnest_first(self):
        rows = [
            {"department": "compliance", "doc_type": "policy",
             "documents": 2, "chunks": 5, "last_added": "2026-08-01"},
            {"department": "general", "doc_type": "sop",
             "documents": 4, "chunks": 40, "last_added": "2026-08-10"},
            {"department": "general", "doc_type": "SOP",
             "documents": 1, "chunks": None, "last_added": None},
        ]
        result = coverage_by_department(_conn([rows]))
        # NULL chunk sums coerce to 0 (row order comes from SQL; mock preserves input)
        assert result[2]["chunks"] == 0
        # expected flag is case-insensitive against the doc type
        assert result[0]["expected"] is True
        assert result[1]["expected"] is True
        assert all(r["documents"] >= 1 for r in result)

    def test_sql_orders_by_chunks_ascending(self):
        conn = _conn([[]])
        coverage_by_department(conn)
        cur = conn.cursor.return_value.__enter__.return_value
        sql = cur.execute.call_args.args[0]
        assert "ORDER BY chunks ASC" in sql
        assert "approval_status = 'approved'" in sql


class TestEmptyCells:
    def test_returns_cells_without_approved_docs(self):
        cells = [
            {"department": "general", "doc_type": "faq"},
        ]
        assert empty_cells(_conn([cells])) == cells

    def test_sql_excludes_cells_with_approved_documents(self):
        conn = _conn([[]])
        empty_cells(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "NOT EXISTS" in sql


class TestBuildCoverageReport:
    def test_combines_both_sections(self):
        report = build_coverage_report(
            _conn([
                [{"department": "g", "doc_type": "sop", "documents": 1,
                  "chunks": 3, "last_added": None}],
                [{"department": "g", "doc_type": "faq"}],
            ])
        )
        assert len(report["coverage"]) == 1
        assert report["empty_cells"][0]["doc_type"] == "faq"
