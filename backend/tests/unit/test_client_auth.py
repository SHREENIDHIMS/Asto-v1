"""Unit tests for client audience auth + RBAC (Phase C).

Covers: JWT audience/client_id claims, client login token shape,
fail-closed role checks for client tokens, and the client audience
search filter.
"""

from __future__ import annotations

import pytest

from app.auth.jwt_handler import create_token, verify_token
from app.auth.permissions import require_role
from app.auth.rbac import is_admin
from fastapi import HTTPException
from app.search.metadata_filters import get_search_filter


class TestClientJWTCreation:
    def test_staff_token_has_audience_staff(self):
        token = create_token(
            subject="1", role="admin", department="general",
            allowed_departments=["general"], audience="staff",
        )
        payload = verify_token(token)
        assert payload is not None
        assert payload["audience"] == "staff"
        assert "client_id" not in payload

    def test_client_token_has_audience_and_client_id(self):
        token = create_token(
            subject="7", role="client", audience="client", client_id=7,
        )
        payload = verify_token(token)
        assert payload is not None
        assert payload["audience"] == "client"
        assert payload["client_id"] == 7
        assert payload["role"] == "client"

    def test_client_token_default_allowed_departments_empty(self):
        token = create_token(subject="7", role="client", audience="client", client_id=7)
        payload = verify_token(token)
        assert payload["allowed_departments"] == []


class TestClientRequireRole:
    def test_client_token_denied_for_admin_action(self):
        user = {"audience": "client", "role": "client", "client_id": 7}
        with pytest.raises(HTTPException) as exc:
            require_role(user, "admin")
        assert exc.value.status_code == 403

    def test_client_token_denied_for_loan_officer_action(self):
        user = {"audience": "client", "role": "client", "client_id": 7}
        with pytest.raises(HTTPException) as exc:
            require_role(user, "loan_officer")
        assert exc.value.status_code == 403

    def test_unknown_role_fails_closed(self):
        user = {"audience": "staff", "role": "mystery_role", "department": "general"}
        with pytest.raises(HTTPException) as exc:
            require_role(user, "admin")
        assert exc.value.status_code == 403

    def test_admin_still_passes(self):
        user = {"audience": "staff", "role": "admin", "department": "general"}
        require_role(user, "admin")  # should not raise

    def test_none_user_denied(self):
        with pytest.raises(HTTPException):
            require_role(None, "admin")


class TestClientAudienceRBAC:
    def test_client_is_not_admin(self):
        user = {"audience": "client", "role": "client", "client_id": 7}
        assert is_admin(user) is False

    def test_client_search_filter_own_documents(self):
        clause, params = get_search_filter(
            {"audience": "client", "client_id": 42, "role": "client"}
        )
        assert "d.client_id = %s" in clause
        assert params == [42]

    def test_client_without_client_id_denied(self):
        clause, params = get_search_filter({"audience": "client", "role": "client"})
        assert clause == "1=0"


class TestStaffTokenRegression:
    def test_staff_token_still_works_for_rbac(self):
        token = create_token(
            subject="1", role="loan_officer", department="general",
            allowed_departments=["general"],
        )
        payload = verify_token(token)
        assert payload is not None
        assert payload["role"] == "loan_officer"
        assert payload["department"] == "general"
