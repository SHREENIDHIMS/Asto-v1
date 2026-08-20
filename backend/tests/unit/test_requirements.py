"""Unit tests for case document requirements (K1).

Covers the case-type inference and the checklist derivation selecting the
correct default requirement set (the regression: the SELECT never fetched
``case_number`` so every case resolved to "purchase").
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.documents.requirements import DEFAULT_REQUIREMENTS, _infer_case_type


class TestInferCaseType:
    def test_purchase_prefix(self):
        assert _infer_case_type({"case_number": "PUR-2026-0012"}) == "purchase"

    def test_refinance_prefix(self):
        assert _infer_case_type({"case_number": "REF-2026-0007"}) == "refinance"

    def test_home_equity_prefix(self):
        assert _infer_case_type({"case_number": "HEL-2026-0003"}) == "home equity"

    def test_unknown_prefix_defaults_to_purchase(self):
        assert _infer_case_type({"case_number": "MSC-2026-0099"}) == "purchase"
        assert _infer_case_type({"case_number": ""}) == "purchase"
        assert _infer_case_type({}) == "purchase"


class TestDeriveChecklist:
    def _conn(self, case_row: dict, approved: list[dict] | None = None):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.side_effect = [
            case_row,                     # cases lookup
            *(approved if approved else []),
        ]
        cur.fetchall.return_value = approved or []
        return conn

    def test_case_number_is_selected_and_drives_type(self):
        conn = self._conn(
            {"id": 1, "client_id": 7, "property_id": 9, "status": "active",
             "case_number": "REF-2026-0001"},
            approved=[],
        )
        from app.documents.requirements import derive_case_checklist

        result = derive_case_checklist(conn, 1)

        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert "case_number" in calls[0]
        # Refinance default set (not purchase).
        names = [r["name"] for r in result]
        assert "Current Mortgage Statement" in names
        assert "Purchase Agreement" not in names
        assert len(result) == len(DEFAULT_REQUIREMENTS["refinance"])

    def test_matching_approved_document_is_approved_status(self):
        conn = self._conn(
            {"id": 1, "client_id": 7, "property_id": 9, "status": "active",
             "case_number": "PUR-2026-0001"},
            approved=[{"id": 10, "title": "Purchase Agreement", "version": 1,
                       "approved_by": 2, "approved_at": None}],
        )
        conn.cursor.return_value.fetchone.side_effect = [
            {"id": 1, "client_id": 7, "property_id": 9, "status": "active",
             "case_number": "PUR-2026-0001"},
        ]
        from app.documents.requirements import derive_case_checklist

        result = derive_case_checklist(conn, 1)
        purchase_agreement = next(r for r in result if r["name"] == "Purchase Agreement")
        assert purchase_agreement["status"] == "approved"
        assert purchase_agreement["has_document"] is True

    def test_unknown_case_returns_empty(self):
        conn = self._conn(None)
        from app.documents.requirements import derive_case_checklist

        assert derive_case_checklist(conn, 999) == []