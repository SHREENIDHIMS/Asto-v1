"""Tests for J6 — document popularity analytics aggregation.

Pure helpers (_rank_popularity) plus mocked DB-flow tests for the endpoint.
DB-backed tests live in tests/integration/test_document_popularity.py
(the unit conftest autouse-mocks every acquire call).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.v1.analytics import _rank_popularity, document_popularity
from app.dependencies import require_auth
from fastapi.testclient import TestClient

from app.main import app


def _row(doc_id, title, answer, no_answer, distinct, pos, neg):
    return {
        "doc_id": doc_id,
        "title": title,
        "department": "general",
        "answer_count": answer,
        "no_answer_count": no_answer,
        "distinct_users": distinct,
        "positive_count": pos,
        "negative_count": neg,
    }


class TestRankPopularity:
    def test_positive_ratio(self):
        rows = [_row(1, "Doc A", 10, 0, 3, 8, 2)]
        ranked = _rank_popularity(rows)
        assert ranked["top_documents"][0]["positive_ratio"] == 0.8
        assert ranked["underperforming_documents"] == []

    def test_ranked_by_answer_count(self):
        rows = [
            _row(1, "Doc A", 3, 0, 1, 3, 0),
            _row(2, "Doc B", 10, 0, 1, 5, 5),
        ]
        ranked = _rank_popularity(rows)
        assert ranked["top_documents"][0]["doc_id"] == 2
        assert ranked["top_documents"][1]["doc_id"] == 1

    def test_underperforming_negative_reviews(self):
        # 1 answer, 1 negative, 0 positive -> ratio 0 < 0.5
        rows = [_row(1, "Doc A", 5, 0, 2, 0, 1)]
        ranked = _rank_popularity(rows)
        assert len(ranked["underperforming_documents"]) == 1

    def test_underperforming_low_signal(self):
        # 1 answer, 1 no_answer (no_answer >= answer and answer <= 2)
        rows = [_row(1, "Doc A", 1, 1, 1, 0, 0)]
        ranked = _rank_popularity(rows)
        assert len(ranked["underperforming_documents"]) == 1

    def test_not_underperforming_high_signal(self):
        # 5 answers, no negatives -> fine
        rows = [_row(1, "Doc A", 5, 0, 2, 5, 0)]
        ranked = _rank_popularity(rows)
        assert ranked["underperforming_documents"] == []


STAFF_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general"],
}


def _client():
    return TestClient(app)


class TestDocumentPopularityEndpoint:
    def test_endpoint_requires_admin(self):
        from app.dependencies import require_auth

        client_user = {
            "id": 7, "email": "c@asto.local", "audience": "client",
            "role": "client", "client_id": 7,
            "department": None, "allowed_departments": [],
        }
        app.dependency_overrides[require_auth] = lambda: client_user
        try:
            response = _client().get("/api/v1/analytics/document-popularity")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_endpoint_returns_ranked(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [
            _row(1, "Popular Doc", 10, 1, 4, 8, 2),
            _row(2, "Weak Doc", 1, 1, 1, 0, 1),
        ]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _client().get("/api/v1/analytics/document-popularity?limit=5")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["top_documents"][0]["title"] == "Popular Doc"
        assert len(body["underperforming_documents"]) == 1
        assert body["underperforming_documents"][0]["doc_id"] == 2
