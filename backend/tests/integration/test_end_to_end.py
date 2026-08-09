"""End-to-end integration test for the full search pipeline.

Tests: process_query → search_knowledge_base → rank_fusion →
       build_response_package → route_by_confidence → validate_package → audit_log

Requires a live Postgres instance with the asto_assistant schema.
Skips gracefully if no DB connection is available.
"""

from __future__ import annotations

import pytest

from app.auth.rbac import resolve_user_departments
from app.config import settings
from app.knowledge_gap.gap_detector import detect_and_log
from app.query_processing.pipeline import process_query
from app.ranking.rrf import rank_fusion
from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import build_response_package
from app.response.validation import validate_package
from app.search.hybrid_orchestrator import search_knowledge_base


def _db_available() -> bool:
    """Check if a database connection is possible."""
    try:
        from app.db.postgres.session import ping
        return ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Requires a running Postgres instance with asto_assistant schema",
)


# --- Benchmark user (admin scope) for integration tests ---
BENCHMARK_USER = {
    "id": 1,
    "role": "super_admin",
    "department": "general",
    "allowed_departments": ["general"],
}


@pytest.fixture(scope="module")
def seeded_db():
    """Seed test data for integration tests, then clean up."""
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema
    from evaluation.datasets.seed_benchmark_data import seed_benchmark_data, clear_benchmark_data

    ensure_schema()
    clear_benchmark_data()
    topic_mapping = seed_benchmark_data()
    yield topic_mapping
    clear_benchmark_data()


class TestEndToEndSearchPipeline:
    """Full pipeline integration: query → search → package → validate."""

    def test_full_pipeline_credit_score(self, seeded_db):
        """Query about credit scores should retrieve relevant chunks."""
        query = "what is the minimum credit score"

        plan = process_query(query)
        assert len(plan.sub_queries) >= 1

        user_depts = resolve_user_departments(BENCHMARK_USER)
        from app.db.postgres.session import acquire

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=[sq.expanded for sq in plan.sub_queries],
                user=BENCHMARK_USER,
            )

        assert len(result.candidates) > 0

        chunk_lookup = {c.chunk_id: c.__dict__ for c in result.candidates}
        bm25_ranked = sorted(
            [(c.chunk_id, c.bm25_score) for c in result.candidates],
            key=lambda x: x[1], reverse=True,
        )
        vector_ranked = sorted(
            [(c.chunk_id, c.vec_score) for c in result.candidates],
            key=lambda x: x[1], reverse=True,
        )
        ranked = rank_fusion(bm25_ranked, vector_ranked, chunk_lookup)

        assert len(ranked) > 0
        assert ranked[0].rrf_score > 0

        package = build_response_package(
            candidates=ranked,
            query_text=query,
            user_departments=user_depts,
        )
        package.routing = route_by_confidence(package.confidence)

        assert package.response_id
        assert package.title
        assert len(package.excerpts) > 0
        assert 0 <= package.confidence <= 100

        # Validate RBAC + approval checks pass
        valid, reason = validate_package(package, BENCHMARK_USER)
        assert valid, f"Package validation failed: {reason}"

        # Verify excerpts trace back to source chunks
        for excerpt in package.excerpts:
            assert excerpt.text
            assert excerpt.source.chunk_id > 0
            assert excerpt.source.title

    def test_pipeline_no_answer_query(self, seeded_db):
        """A query with no matching content routes to 'no_answer'."""
        query = "asdfqwer zxcvbnm"

        plan = process_query(query)

        from app.db.postgres.session import acquire

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=[sq.expanded for sq in plan.sub_queries],
                user=BENCHMARK_USER,
            )

        chunk_lookup = {c.chunk_id: c.__dict__ for c in result.candidates}
        bm25_ranked = sorted(
            [(c.chunk_id, c.bm25_score) for c in result.candidates],
            key=lambda x: x[1], reverse=True,
        )
        vector_ranked = sorted(
            [(c.chunk_id, c.vec_score) for c in result.candidates],
            key=lambda x: x[1], reverse=True,
        )
        ranked = rank_fusion(bm25_ranked, vector_ranked, chunk_lookup)

        package = build_response_package(
            candidates=ranked,
            query_text=query,
            user_departments=resolve_user_departments(BENCHMARK_USER),
        )
        package.routing = route_by_confidence(package.confidence)

        # Low confidence → no_answer or partial
        assert package.routing in ("no_answer", "partial")

        # Gap detection should be triggered but not crash
        intent = plan.sub_queries[0].intent if plan.sub_queries else "general"
        if package.routing in ("no_answer", "partial"):
            detect_and_log(
                query=query,
                intent=intent,
                confidence=package.confidence,
            )

    def test_pipeline_rbac_restriction(self, seeded_db):
        """A restricted user should only see general-department chunks."""
        restricted_user = {
            "id": "restricted_user",
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": [],  # only general
        }

        query = "what is the minimum credit score"
        plan = process_query(query)

        from app.db.postgres.session import acquire

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=[sq.expanded for sq in plan.sub_queries],
                user=restricted_user,
            )

        # All returned candidates must be from "general" department
        for c in result.candidates:
            assert c.department == "general", (
                f"RBAC leak: user saw chunk from {c.department}"
            )

    def test_pipeline_audit_log_created(self, seeded_db):
        """Verify audit logging captures the query and retrieved IDs."""
        from app.audit.audit_logger import AuditLogEntry, log_query
        from app.db.postgres.session import acquire

        query = "what is the minimum credit score"
        plan = process_query(query)

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=[sq.expanded for sq in plan.sub_queries],
                user=BENCHMARK_USER,
            )

        chunk_lookup = {c.chunk_id: c.__dict__ for c in result.candidates}
        bm25_ranked = sorted(
            [(c.chunk_id, c.bm25_score) for c in result.candidates],
            key=lambda x: x[1], reverse=True,
        )
        vector_ranked = sorted(
            [(c.chunk_id, c.vec_score) for c in result.candidates],
            key=lambda x: x[1], reverse=True,
        )
        ranked = rank_fusion(bm25_ranked, vector_ranked, chunk_lookup)

        package = build_response_package(
            candidates=ranked,
            query_text=query,
            user_departments=resolve_user_departments(BENCHMARK_USER),
        )
        package.routing = route_by_confidence(package.confidence)

        entry = AuditLogEntry(
            user_id=BENCHMARK_USER["id"],
            query=query,
            sub_queries=[sq.display for sq in plan.sub_queries],
            retrieved_ids=[c.chunk_id for c in ranked[:25]],
            confidence=round(package.confidence, 1),
            response_id=package.response_id,
            outcome=package.routing,
            latency_ms=50.0,
        )
        log_query(entry)

        # Verify the audit entry was written to the DB
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT query, confidence, outcome, response_id FROM audit_log "
                    "WHERE response_id = %s ORDER BY created_at DESC LIMIT 1",
                    (package.response_id,),
                )
                row = cur.fetchone()

        assert row is not None, "Audit log entry not found in DB"
        assert row["query"] == query
        assert row["confidence"] == round(package.confidence, 1)
        assert row["outcome"] == package.routing

    def test_document_path_stream_emits_sentence_events(self, seeded_db):
        """SSE document-path stream pushes a ``sentence`` event per extractive
        summary sentence, then a ``result`` event with the full package."""
        import json

        from fastapi.testclient import TestClient

        from app.auth.jwt_handler import create_token
        from app.dependencies import require_auth
        from app.main import app

        token = create_token(
            subject="benchmark",
            role="super_admin",
            department="general",
            allowed_departments=["general"],
        )

        app.dependency_overrides[require_auth] = lambda: BENCHMARK_USER
        try:
            client = TestClient(app)
            with client.stream(
                "POST",
                "/api/v1/search/stream",
                json={"query": "what is the minimum credit score"},
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                body = "".join(response.iter_text())
        finally:
            app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        event_types = []
        sentence_events = []
        result_event = None
        for part in body.split("\n\n"):
            if not part.strip():
                continue
            lines = part.splitlines()
            event = next(
                (l[len("event: ") :] for l in lines if l.startswith("event: ")),
                "message",
            )
            data = next(
                (l[len("data: ") :] for l in lines if l.startswith("data: ")),
                None,
            )
            event_types.append(event)
            if event == "sentence":
                sentence_events.append(data)
            elif event == "result":
                result_event = data

        assert event_types[0] == "status"
        assert event_types[-1] == "result"

        result = json.loads(result_event)
        # A sentence event exists for each extractive summary sentence.
        assert len(sentence_events) == len(result["summary"])
        if sentence_events:
            first = json.loads(sentence_events[0])
            assert first["text"]
            assert first["source"]
        assert result["retrieval_path"] == "document"

