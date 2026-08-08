"""Backfill embeddings for existing chunks that were seeded without vectors."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from app.db.postgres.session import acquire
from app.documents.embedding import generate_embeddings

BATCH_SIZE = 32


def backfill() -> None:
    with acquire() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT id, content FROM document_chunks WHERE embedding IS NULL "
                "ORDER BY id"
            )
            rows = cur.fetchall()

    if not rows:
        print("No chunks need embeddings.")
        return

    print(f"Generating embeddings for {len(rows)} chunks...")
    texts = [r["content"] for r in rows]
    embeddings = generate_embeddings(texts)

    updated = 0
    with acquire() as conn:
        with conn.cursor() as cur:
            for row, embedding in zip(rows, embeddings):
                cur.execute(
                    "UPDATE document_chunks SET embedding = %s WHERE id = %s",
                    (embedding, row["id"]),
                )
                updated += cur.rowcount
                if updated % BATCH_SIZE == 0:
                    conn.commit()
            conn.commit()

    print(f"Backfilled embeddings for {updated} chunks.")


if __name__ == "__main__":
    backfill()
