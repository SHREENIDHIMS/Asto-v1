"""Unit tests for Phase F6 client<->staff messaging endpoints.

Covers: route wiring, auth requirements, client-only scoping, staff
assignment scoping (enforced in SQL), create/list/send flows, and the
sender_name JOIN on message reads.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

CLIENT_USER = {
    "id": 7,
    "email": "client@asto.local",
    "full_name": "Client User",
    "is_active": True,
    "audience": "client",
    "client_id": 7,
    "role": "client",
    "department": None,
    "allowed_departments": [],
}

STAFF_USER = {
    "id": 3,
    "email": "staff@asto.local",
    "full_name": "Staff User",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "loans",
    "allowed_departments": [],
}

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general", "compliance"],
}


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth
    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _teardown():
    from app.main import app
    from app.dependencies import require_auth
    app.dependency_overrides.pop(require_auth, None)


CONVERSATION_ROW = {
    "id": 1,
    "case_id": 10,
    "client_id": 7,
    "subject": "Loan docs",
    "created_at": None,
    "updated_at": None,
}

MESSAGE_ROW = {
    "id": 1,
    "conversation_id": 1,
    "sender_type": "client",
    "sender_user_id": None,
    "sender_client_id": 7,
    "sender_name": "Client User",
    "body": "Hello",
    "created_at": None,
}


class TestMessagingRoutes:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/client/conversations" in paths
        assert "/api/v1/client/conversations/{conversation_id}/messages" in paths
        assert "/api/v1/staff/conversations" in paths
        assert "/api/v1/staff/conversations/{conversation_id}/messages" in paths

    def test_client_conversations_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/client/conversations").status_code == 401

    def test_staff_conversations_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/staff/conversations").status_code == 401

    def test_client_conversations_denies_staff(self):
        try:
            response = _authorized(STAFF_USER).get("/api/v1/client/conversations")
        finally:
            _teardown()
        assert response.status_code == 403

    def test_staff_conversations_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/staff/conversations")
        finally:
            _teardown()
        assert response.status_code == 403


class TestClientConversations:
    def test_list_scopes_to_client_id(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [CONVERSATION_ROW]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).get("/api/v1/client/conversations")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["conversations"][0]["subject"] == "Loan docs"
        sql = cur.execute.call_args.args[0]
        assert "WHERE c.client_id = %s" in sql
        assert cur.execute.call_args.args[1] == (7,)

    def test_create_conversation(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = CONVERSATION_ROW
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).post(
                    "/api/v1/client/conversations",
                    json={"subject": "Loan docs", "case_id": 10},
                )
            finally:
                _teardown()

        assert response.status_code == 201
        data = response.json()
        assert data["conversation"]["subject"] == "Loan docs"
        insert_sql = cur.execute.call_args.args[0]
        assert "INSERT INTO conversations" in insert_sql
        assert cur.execute.call_args.args[1][1] == 7

    def test_create_conversation_rejects_blank_subject(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).post(
                    "/api/v1/client/conversations",
                    json={"subject": "   "},
                )
            finally:
                _teardown()
        assert response.status_code == 422

    def test_list_messages_validates_ownership(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None  # not owned -> 404
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).get(
                    "/api/v1/client/conversations/999/messages"
                )
            finally:
                _teardown()
        assert response.status_code == 404

    def test_send_message_inserts_with_client_sender(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = MESSAGE_ROW
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).post(
                    "/api/v1/client/conversations/1/messages",
                    json={"body": "Hello"},
                )
            finally:
                _teardown()

        assert response.status_code == 201
        data = response.json()
        assert data["message"]["body"] == "Hello"
        assert data["message"]["sender_type"] == "client"
        insert_sql = next(
            c.args[0] for c in cur.execute.call_args_list
            if c.args[0].startswith("INSERT INTO messages")
        )
        assert "sender_client_id" in insert_sql

    def test_send_message_rejects_blank_body(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).post(
                    "/api/v1/client/conversations/1/messages",
                    json={"body": ""},
                )
            finally:
                _teardown()
        assert response.status_code == 422


class TestStaffConversations:
    def test_list_admin_sees_all(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [CONVERSATION_ROW]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/staff/conversations")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["conversations"][0]["subject"] == "Loan docs"
        sql = cur.execute.call_args.args[0]
        assert "staff_client_assignments" not in sql

    def test_list_staff_scopes_to_assignments(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [CONVERSATION_ROW]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get("/api/v1/staff/conversations")
            finally:
                _teardown()

        assert response.status_code == 200
        sql = cur.execute.call_args.args[0]
        assert "staff_client_assignments" in sql
        assert cur.execute.call_args.args[1] == (3,)

    def test_staff_send_message_scopes_assignment(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = MESSAGE_ROW
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/conversations/1/messages",
                    json={"body": "Reply"},
                )
            finally:
                _teardown()

        assert response.status_code == 201
        data = response.json()
        assert data["message"]["sender_type"] == "client"
        ownership_sql = cur.execute.call_args_list[0].args[0]
        assert "JOIN staff_client_assignments" in ownership_sql

    def test_staff_cannot_read_unassigned_conversation(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get(
                    "/api/v1/staff/conversations/999/messages"
                )
            finally:
                _teardown()
        assert response.status_code == 404

    def test_staff_message_read_joins_sender_name(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = CONVERSATION_ROW  # access check passes
        cur.fetchall.return_value = [MESSAGE_ROW]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/staff/conversations/1/messages"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["messages"][0]["sender_name"] == "Client User"
