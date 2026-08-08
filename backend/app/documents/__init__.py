"""Document ingestion pipeline package.

Splits into:
- upload.py — API endpoint that validates and writes files to storage/pending/
- ingest_batch.py — offline entry point that processes storage/pending/
- validation.py — file type/size checks
- text_extraction.py — PDF/text extraction
- chunking/structural_chunker.py — structure-aware chunking
- metadata_extraction.py — document metadata extraction
- entity_extraction.py — domain entity extraction (dictionary-based)
- embedding.py — FastEmbed-based embedding generation
- indexing.py — writes rows + pgvector to Postgres

Per CLAUDE.md rule 5: ingestion logic lives ONLY in ingest_batch.py,
never in a request handler. The API's upload endpoint only validates
and writes to storage/pending/.
"""
