"""Indexing — write document chunks to Postgres.

Writes both metadata rows (document_chunks content, section, etc.) and
vector embeddings to the document_chunks table. Handles deduplication
via content_hash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from psycopg import Connection

from app.db.postgres.models import content_hash
from app.documents.chunking.structural_chunker import Chunk

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    document_id: int
    chunks_indexed: int
    chunks_skipped: int  # duplicates


def index_document(
    conn: Connection,
    doc_title: str,
    doc_type: str,
    department: str,
    source_path: str | None,
    chunks: Sequence[Chunk],
    embeddings: Sequence[list[float]] | None = None,
    approval_status: str = "pending",
    client_id: int | None = None,
    property_id: int | None = None,
) -> IndexResult:
    """Insert a document and its chunks into Postgres.

    Assumes the schema has already been created (ensure_schema()).

    New documents enter the approval workflow as ``pending`` and are not
    searchable until an admin approves them (search filters on
    ``is_approved = true``). Pass ``approval_status="approved"`` to skip
    the workflow (e.g. for trusted seed/backfill data).

    ``client_id`` / ``property_id`` scope the document to a client and
    (optionally) a property — used for client-uploaded documents.
    """
    assert len(chunks) == (len(embeddings) if embeddings else 0) or not embeddings
    is_approved = approval_status == "approved"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents
                (title, doc_type, department, source_path,
                 client_id, property_id, approval_status, is_approved)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (doc_title, doc_type, department, source_path,
             client_id, property_id, approval_status, is_approved),
        )
        document_id = cur.fetchone()["id"]
        logger.info(
            "Indexing document '%s' (id=%d, approval_status=%s)",
            doc_title, document_id, approval_status,
        )

    indexed = 0
    skipped = 0
    seen_hashes: set[str] = set()

    for i, chunk in enumerate(chunks):
        ch = content_hash(chunk.content)
        if ch in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(ch)

        embedding = (
            embeddings[i] if embeddings else None
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_chunks
                    (document_id, content, content_hash, embedding,
                     section, chunk_type, department,
                     approval_status, is_approved)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_hash) DO NOTHING
                """,
                (
                    document_id,
                    chunk.content,
                    ch,
                    embedding,
                    chunk.section,
                    chunk.chunk_type,
                    department,
                    approval_status,
                    is_approved,
                ),
            )
            if cur.rowcount > 0:
                indexed += 1
            else:
                skipped += 1

    conn.commit()
    logger.info("Document %d: %d chunks indexed, %d skipped", document_id, indexed, skipped)
    return IndexResult(document_id, indexed, skipped)
