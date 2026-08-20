"""Unit tests for dual-audience RBAC scoping (Phase B).

Covers: client audience (own documents only), staff with assigned clients
(dept ∩ assigned), staff with no assignments (company docs only), admin
(no filter), and the latent department bug in Source/validation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.response.package_builder import Excerpt, ResponsePackage, Source
from app.response.validation import validate_package
from app.search.metadata_filters import get_search_filter


class TestClientAudienceFilter:
    def test_client_sees_only_own_documents(self):
        clause, params = get_search_filter(
            {"audience": "client", "client_id": 42, "role": "client"}
        )
        assert "d.client_id = %s" in clause
        assert params == [42]

    def test_client_without_client_id_denied(self):
        clause, params = get_search_filter({"audience": "client"})
        assert clause == "1=0"
        assert params == []


class TestStaffClientScoping:
    def test_staff_with_assigned_clients_sees_company_and_assigned(self):
        clause, params = get_search_filter(
            {
                "id": 1,
                "role": "loan_officer",
                "department": "general",
                "allowed_departments": ["compliance"],
            },
            assigned_client_ids=[7, 9],
        )
        assert "d.client_id IS NULL" in clause
        assert "d.client_id = ANY(ARRAY[%s,%s]::bigint[])" in clause
        assert params == ["compliance", "general", 7, 9]

    def test_staff_with_no_assignments_sees_company_only(self):
        clause, params = get_search_filter(
            {
                "id": 1,
                "role": "loan_officer",
                "department": "general",
                "allowed_departments": [],
            },
            assigned_client_ids=[],
        )
        assert "d.client_id IS NULL" in clause
        assert params == ["general"]

    def test_staff_resolves_assignments_from_conn(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [{"client_id": 5}, {"client_id": 8}]
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        clause, params = get_search_filter(
            {
                "id": 3,
                "role": "loan_officer",
                "department": "general",
                "allowed_departments": [],
            },
            conn=conn,
        )
        assert "ANY(ARRAY[%s,%s]" in clause
        assert params == ["general", 5, 8]

    def test_admin_still_unfiltered(self):
        clause, params = get_search_filter(
            {"role": "super_admin", "department": "general", "allowed_departments": []}
        )
        assert clause == ""
        assert params == []


class TestValidationClientScope:
    def _package_with_client(self, client_id):
        return ResponsePackage(
            response_id="test",
            title="Test",
            excerpts=[
                Excerpt(
                    text="content",
                    source=Source(
                        chunk_id=1,
                        document_id=1,
                        title="Doc",
                        section=None,
                        chunk_type="paragraph",
                        is_approved=True,
                        document_version=1,
                        department="general",
                        client_id=client_id,
                    ),
                    confidence=90.0, bm25_score=0.9, vec_score=0.9,
                )
            ],
            confidence=90.0,
            routing="answer",
        )

    def test_client_own_chunk_passes(self):
        user = {"audience": "client", "client_id": 42}
        valid, _ = validate_package(self._package_with_client(42), user)
        assert valid is True

    def test_client_foreign_chunk_fails(self):
        user = {"audience": "client", "client_id": 42}
        valid, reason = validate_package(self._package_with_client(99), user)
        assert valid is False
        assert "not" in reason

    def test_client_company_wide_doc_passes(self):
        """Regression (P1-16): a company-wide doc (client_id IS NULL) must
        never be treated as an RBAC violation → 500. It is visible to every
        client; only a doc scoped to a *different* client is a violation."""
        user = {"audience": "client", "client_id": 42}
        valid, reason = validate_package(self._package_with_client(None), user)
        assert valid is True
        assert reason == "OK"

    def test_staff_company_wide_doc_passes(self):
        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": [],
        }
        valid, _ = validate_package(self._package_with_client(None), user)
        assert valid is True

    def test_staff_unassigned_scoped_doc_fails_when_assignment_known(self):
        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": [],
        }
        valid, reason = validate_package(
            self._package_with_client(8),
            user,
            assigned_client_ids=[5],
        )
        assert valid is False
        assert "not assigned" in reason

    def test_staff_assigned_scoped_doc_passes(self):
        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": [],
        }
        valid, _ = validate_package(
            self._package_with_client(8),
            user,
            assigned_client_ids=[5, 8],
        )
        assert valid is True

    def test_staff_department_safety_net_uses_source_department(self):
        """Regression: Source must carry department for the validation net."""
        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": [],
        }
        package = self._package_with_client(None)
        package.excerpts[0].source.department = "underwriting"
        valid, reason = validate_package(package, user)
        assert valid is False
        assert "underwriting" in reason
