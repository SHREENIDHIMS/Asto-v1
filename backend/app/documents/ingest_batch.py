"""Document ingestion batch pipeline — entry point.

Runs as a standalone process (invoked via infra/scripts/run_ingestion.sh),
NOT inside the FastAPI request handler. Loads the embedding model,
processes files in storage/pending/, and writes indexed chunks to Postgres.

Pipeline order (per SKILL.md Phase 2 and Final_System_Design.md §6):
  validation → OCR (optional fallback) → text_extraction →
  structural_chunking (tables, checklists, sections, paragraphs) →
  metadata_extraction → entity_extraction (light) →
  embedding → indexing

Usage:
    python -m app.documents.ingest_batch --queue-dir /path/to/pending
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.config import settings
from app.db.postgres.schema import ensure_schema
from app.db.postgres.session import acquire
from app.documents.chunking.structural_chunker import StructuralChunker
from app.documents.embedding import generate_embeddings
from app.documents.entity_extraction import extract_entities
from app.documents.indexing import index_document
from app.documents.metadata_extraction import extract_metadata
from app.documents.text_extraction import extract_text, ExtractedText

logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _move_to_processed(file_path: Path) -> None:
    """Move processed file to the processed directory."""
    processed_dir = Path(settings.storage_processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    dest = processed_dir / file_path.name
    try:
        file_path.rename(dest)
        logger.info("Moved %s → %s", file_path, dest)
    except FileNotFoundError:
        logger.warning("File already moved: %s", file_path)


def _try_ocr_fallback(file_path: Path, extracted: ExtractedText) -> ExtractedText | None:
    """If pdfplumber returned empty/low-quality text, try OCR via pytesseract.

    Only applies to PDFs. Returns a new ExtractedText with OCR text,
    or None if OCR is unavailable or fails.
    """
    if file_path.suffix.lower() != ".pdf":
        return None

    ocr_text = extracted.text.strip()
    if len(ocr_text) > 50:  # enough text already extracted
        return None

    try:
        from app.documents.ocr import ocr_pdf_pages

        ocr_pages = ocr_pdf_pages(file_path)
        if ocr_pages:
            full_text = "\n".join(ocr_pages)
            if full_text.strip():
                logger.info("OCR fallback produced %d chars for %s", len(full_text), file_path.name)
                return ExtractedText(
                    text=full_text,
                    pages=ocr_pages,
                    source_format=extracted.source_format,
                )
    except Exception as exc:
        logger.warning("OCR fallback failed for %s: %s", file_path.name, exc)

    return None


def process_file(file_path: Path) -> bool:
    """Process a single document file through the full pipeline."""
    logger.info("Processing: %s", file_path.name)

    try:
        extracted = extract_text(file_path)
    except Exception as e:
        logger.error("Text extraction failed for %s: %s", file_path.name, e)
        return False

    # Optional OCR fallback for scanned PDFs with low text extraction
    if file_path.suffix.lower() == ".pdf":
        ocr_result = _try_ocr_fallback(file_path, extracted)
        if ocr_result is not None:
            extracted = ocr_result

    metadata = extract_metadata(extracted, file_path)
    entities = extract_entities(extracted.text)
    logger.info(
        "Metadata: title=%s, type=%s, %d lenders, %d products",
        metadata.title,
        metadata.doc_type,
        len(entities.lenders),
        len(entities.products),
    )

    chunker = StructuralChunker(max_tokens=settings.max_excerpt_chars // 2)
    chunks = list(chunker.chunk(extracted))
    if not chunks:
        logger.warning("No chunks produced for %s", file_path.name)
        return False

    logger.info("Produced %d chunks", len(chunks))

    embeddings = None
    if settings.embedding_enabled:
        try:
            chunk_texts = [c.content for c in chunks]
            embeddings = generate_embeddings(chunk_texts)
        except Exception as e:
            logger.error("Embedding generation failed for %s: %s", file_path.name, e)
            embeddings = None

    with acquire() as conn:
        result = index_document(
            conn=conn,
            doc_title=metadata.title,
            doc_type=metadata.doc_type,
            department=metadata.department,
            source_path=metadata.source_path,
            chunks=chunks,
            embeddings=embeddings,
        )
        logger.info(
            "Indexed %d, skipped %d for document %d",
            result.chunks_indexed,
            result.chunks_skipped,
            result.document_id,
        )

    return True


def main(queue_dir: str) -> None:
    """Process all files in the queue directory."""
    queue_path = Path(queue_dir)
    if not queue_path.exists():
        logger.error("Queue directory does not exist: %s", queue_path)
        return

    files = [
        f for f in queue_path.iterdir()
        if f.is_file() and f.suffix.lower() in {
            ".pdf", ".txt", ".docx", ".html", ".htm", ".md",
            ".csv", ".xlsx", ".pptx", ".odt", ".rtf", ".epub",
        }
    ]
    if not files:
        logger.info("No files to process in %s", queue_path)
        return

    ensure_schema()

    success = 0
    failed = 0
    for file_path in files:
        if process_file(file_path):
            _move_to_processed(file_path)
            success += 1
        else:
            failed += 1

    logger.info("Batch complete: %d succeeded, %d failed", success, failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Document ingestion batch pipeline")
    parser.add_argument(
        "--queue-dir",
        default=settings.storage_pending_dir,
        help="Directory to scan for pending documents",
    )
    args = parser.parse_args()
    main(args.queue_dir)
