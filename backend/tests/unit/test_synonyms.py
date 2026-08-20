"""Unit tests for audit fix #23 — synonym expansion correctness + caching.

The expansion previously unpacked dict rows by iteration (yielding the literal
keys "canonical"/"alias", never matching), read the full ``synonyms`` table on
every request, and fed only the embedding — the BM25 tsquery was built from the
unexpanded text. These tests cover the fixes: dict-row access, a TTL cache with
inline admin invalidation, and expanded text reaching ``build_tsquery``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.search.hybrid_orchestrator import (
    _expand_query_with_synonyms,
    _load_synonyms,
    invalidate_synonyms_cache,
    search_knowledge_base,
)


@pytest.fixture(autouse=True)
def _reset_synonyms_cache():
    invalidate_synonyms_cache()
    yield
    invalidate_synonyms_cache()


def _conn_with_synonyms(rows: list[dict]) -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    cur.fetchall.return_value = rows
    return conn


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


class TestExpandQueryWithSynonyms:
    def test_matching_alias_appends_canonical(self):
        conn = _conn_with_synonyms(
            [{"canonical": "loan to value", "alias": "ltv"}]
        )
        assert _expand_query_with_synonyms("max ltv", conn) == "max ltv loan to value"

    def test_original_words_never_replaced(self):
        conn = _conn_with_synonyms(
            [
                {"canonical": "loan to value", "alias": "ltv"},
                {"canonical": "debt to income", "alias": "dti"},
            ]
        )
        expanded = _expand_query_with_synonyms("max ltv ratio", conn)
        assert expanded.startswith("max ltv ratio")
        assert "loan to value" in expanded
        # dti does not appear in the query -> not added.
        assert "debt to income" not in expanded

    def test_case_insensitive_alias_match(self):
        conn = _conn_with_synonyms(
            [{"canonical": "mortgage", "alias": "home loan"}]
        )
        assert _expand_query_with_synonyms("HOME LOAN rates", conn) == "HOME LOAN rates mortgage"

    def test_no_match_returns_query_unchanged(self):
        conn = _conn_with_synonyms(
            [{"canonical": "mortgage", "alias": "home loan"}]
        )
        assert _expand_query_with_synonyms("interest rates", conn) == "interest rates"

    def test_empty_synonym_table_unchanged(self):
        assert _expand_query_with_synonyms("anything", _conn_with_synonyms([])) == "anything"


class TestSynonymCache:
    def test_synonyms_table_fetched_once_within_ttl(self):
        conn = _conn_with_synonyms([{"canonical": "a", "alias": "b"}])
        assert _load_synonyms(conn) == (("a", "b"),)
        assert _load_synonyms(conn) == (("a", "b"),)
        assert conn.cursor.return_value.execute.call_count == 1

    def test_invalidate_forces_reload(self):
        conn = _conn_with_synonyms([{"canonical": "a", "alias": "b"}])
        _load_synonyms(conn)
        invalidate_synonyms_cache()
        _load_synonyms(conn)
        assert conn.cursor.return_value.execute.call_count == 2


class TestTsqueryGetsExpandedText:
    def test_combined_text_uses_expanded_primary_query(self):
        conn = _conn()
        conn.cursor.return_value.fetchall.return_value = []

        with (
            patch(
                "app.search.hybrid_orchestrator._expand_query_with_synonyms",
                return_value="mortgage rates home loan",
            ),
            patch(
                "app.search.hybrid_orchestrator.embed_query",
                return_value=[0.1, 0.2],
            ) as embed,
            patch(
                "app.search.hybrid_orchestrator.build_tsquery",
                return_value="mortgage | rates | home | loan",
            ) as build,
            patch(
                "app.search.hybrid_orchestrator.get_search_filter",
                return_value=("", []),
            ),
        ):
            result = search_knowledge_base(
                conn, ["mortgage rates", "second"], user=None
            )

        # The tsquery (built from combined_text) must include the expansion.
        assert build.call_args.args[0] == "mortgage rates home loan second"
        # The embedding still uses the expanded primary query.
        assert embed.call_args.args[0] == "mortgage rates home loan"
        assert result.candidates == []


class TestAdminInvalidationWiring:
    ADMIN_USER = {
        "id": 1, "email": "admin@asto.local", "full_name": "Admin",
        "is_active": True, "audience": "staff", "role": "admin",
        "department": "general", "allowed_departments": ["general"],
    }

    def _client(self):
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: self.ADMIN_USER
        return TestClient(app)

    def _teardown(self):
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides.pop(require_auth, None)

    def test_create_synonym_invalidates_cache(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,  # existence check -> not present
            {"canonical": "loan to value", "alias": "ltv"},  # INSERT RETURNING
        ]

        try:
            with (
                patch("app.db.postgres.session.acquire", return_value=conn),
                patch("app.api.v1.admin.invalidate_synonyms_cache") as invalidate,
            ):
                response = self._client().post(
                    "/api/v1/admin/synonyms",
                    json={"canonical": "loan to value", "alias": "ltv"},
                )
            assert response.status_code == 201
            invalidate.assert_called_once()
        finally:
            self._teardown()

    def test_delete_synonym_invalidates_cache(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 1

        try:
            with (
                patch("app.db.postgres.session.acquire", return_value=conn),
                patch("app.api.v1.admin.invalidate_synonyms_cache") as invalidate,
            ):
                response = self._client().delete(
                    "/api/v1/admin/synonyms/loan%20to%20value/ltv"
                )
            assert response.status_code == 204
            invalidate.assert_called_once()
        finally:
            self._teardown()