"""Integration test for scoped chunk dedup (0003_scoped_chunk_dedup).

Verifies against a live Postgres that ``content_hash`` uniqueness is
scoped to ``(document_id, content_hash)``:

- Re-uploading the same content (version bump) must NOT silently skip every
  chunk: the new active document owns its own chunk rows.
- Two documents sharing verbatim chunk text must coexist without conflicts.

Regression: the previous globally-unique ``content_hash`` made both cases
lose chunks (a re-upload produced an unsearchable zero-chunk document).

Requires a running Postgres; skips gracefully when unavailable.
"""

from __future__ import annotations

import pytest

from app.db.postgres.session import acquire


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

CLIENT_EMAIL = "dedup.client@asto.test"
DOC_TITLE = "Shared Policy Dedup Integration"
UNIQUE_CHUNK = "this chunk text is unique to the dedup integration run 9f3d1a"
BOILERPLATE = "standard boilerplate identical across documents dedup"


@pytest.fixture(scope="module")
def dedup_db():
    """Seed one client, run the scenario, then clean up."""
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    ids: dict[str, int] = {}
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clients (email, full_name, password_hash, is_active) "
                "VALUES (%s, %s, 'x', true) RETURNING id",
                (CLIENT_EMAIL, "Dedup Client"),
            )
            ids["client_id"] = cur.fetchone()["id"]
        conn.commit()

    yield ids

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE client_id = %s", (ids["client_id"],))
            cur.execute("DELETE FROM clients WHERE id = %s", (ids["client_id"],))
        conn.commit()


def _chunk_count(conn, document_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM document_chunks WHERE document_id = %s",
            (document_id,),
        )
        return cur.fetchone()["count"]


def _index(conn, client_id: int, chunks):
    from app.documents.chunking.structural_chunker import Chunk
    from app.documents.indexing import index_document

    chunk_objs = [
        Chunk(content=c, chunk_type="paragraph", section=None, page_number=None)
        for c in chunks
    ]
    return index_document(
        conn=conn,
        doc_title=DOC_TITLE,
        doc_type="policy",
        department="general",
        source_path="/dedup/test.pdf",
        chunks=chunk_objs,
        approval_status="approved",
        client_id=client_id,
    ), chunk_objs


def test_reupload_keeps_chunks_under_new_version(dedup_db):
    from app.db.postgres.session import acquire

    client_id = dedup_db["client_id"]
    chunks = [UNIQUE_CHUNK, BOILERPLATE]

    with acquire() as conn:
        first, _ = _index(conn, client_id, chunks)
        assert first.chunks_indexed == 2, "first upload should index both chunks"
        assert first.chunks_skipped == 0

        # Version bump with byte-identical content.
        second, _ = _index(conn, client_id, chunks)
        assert second.document_id != first.document_id

        # THE regression: the new active document must own its own chunks,
        # not skip them because the old version's rows conflict globally.
        assert second.chunks_indexed == 2, "re-upload must re-index its own chunks"
        assert _chunk_count(conn, first.document_id) == 2
        assert _chunk_count(conn, second.document_id) == 2

        # Only the newest version is active.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_active FROM documents WHERE id IN (%s, %s) ORDER BY id",
                (first.document_id, second.document_id),
            )
            active = {row["is_active"] for row in cur.fetchall()}
        assert active == {False, True}


def test_identical_chunks_across_documents_coexist(dedup_db):
    from app.db.postgres.session import acquire

    client_id = dedup_db["client_id"]
    # Two distinct titles sharing verbatim chunk text must not conflict.
    with acquire() as conn:
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        common = [BOILERPLATE]
        chunk_objs = [
            Chunk(content=c, chunk_type="paragraph", section=None, page_number=None)
            for c in common
        ]
        a = index_document(
            conn=conn, doc_title="Dedup Policy A", doc_type="policy",
            department="general", source_path="/dedup/a.pdf", chunks=chunk_objs,
            approval_status="approved", client_id=client_id,
        )
        b = index_document(
            conn=conn, doc_title="Dedup Policy B", doc_type="policy",
            department="general", source_path="/dedup/b.pdf", chunks=chunk_objs,
            approval_status="approved", client_id=client_id,
        )
        assert a.chunks_indexed == 1
        assert b.chunks_indexed == 1
        assert _chunk_count(conn, a.document_id) == 1
        assert _chunk_count(conn, b.document_id) == 1