"""Unit tests for batch ingestion failure isolation (P2-20).

A single poisoned file must not abort the whole batch: ``process_file``
contains every downstream stage so the ``main`` loop can move on to the
next pending file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.documents.ingest_batch import process_file


class TestProcessFileFailureIsolation:
    def test_extraction_failure_returns_false(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_text("not really a pdf")

        with patch("app.documents.ingest_batch.extract_text", side_effect=RuntimeError("boom")):
            assert process_file(bad) is False

    def test_downstream_failure_returns_false(self, tmp_path):
        good = tmp_path / "good.txt"
        good.write_text("plain text")

        with (
            patch(
                "app.documents.ingest_batch.extract_text",
                return_value=type("E", (), {"text": "hello", "pages": [], "source_format": "txt"})(),
            ),
            patch(
                "app.documents.ingest_batch.extract_metadata",
                side_effect=ValueError("poisoned metadata"),
            ),
        ):
            assert process_file(good) is False

    def test_index_failure_returns_false(self, tmp_path):
        good = tmp_path / "good.txt"
        good.write_text("plain text")

        chunk = type("C", (), {"content": "hello"})()
        extracted = type("E", (), {"text": "hello", "pages": [], "source_format": "txt"})()

        with (
            patch("app.documents.ingest_batch.extract_text", return_value=extracted),
            patch("app.documents.ingest_batch.extract_metadata") as md,
            patch("app.documents.ingest_batch.extract_entities"),
            patch("app.documents.ingest_batch.StructuralChunker") as sc,
            patch("app.documents.ingest_batch.index_document", side_effect=RuntimeError("db down")),
        ):
            md.return_value = type(
                "M", (), {"title": "t", "doc_type": "policy", "department": "general", "source_path": "s"}
            )()
            sc.return_value.chunk.return_value = iter([chunk])
            assert process_file(good) is False

    def test_main_loop_continues_past_poisoned_file(self, tmp_path):
        bad = tmp_path / "bad.txt"
        good = tmp_path / "good.txt"
        bad.write_text("x")
        good.write_text("y")

        with (
            patch("app.documents.ingest_batch.ensure_schema"),
            patch("app.documents.ingest_batch.process_file", side_effect=[False, True]) as pf,
            patch("app.documents.ingest_batch._move_to_processed"),
            patch("app.documents.ingest_batch.settings") as settings,
        ):
            settings.storage_pending_dir = str(tmp_path)
            from app.documents.ingest_batch import main

            main(str(tmp_path))

        assert pf.call_count == 2