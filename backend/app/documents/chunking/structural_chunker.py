"""Structural chunker for document ingestion.

Splits document text into chunks that respect document structure:
- Tables are kept as single chunks (never split mid-table)
- Headings create chunk boundaries
- Paragraphs are grouped into chunks of ~200–500 tokens
- Checklists (bullet/numbered lists) are split into individual items

Uses table_chunker and checklist_chunker for specialized detection
(Final_System_Design.md §6, Final_Tech_Stack.md: "Hybrid Structural Chunking").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from app.documents.chunking.table_chunker import chunk_table
from app.documents.chunking.checklist_chunker import chunk_checklist
from app.documents.text_extraction import ExtractedText


@dataclass
class Chunk:
    content: str
    section: str | None
    chunk_type: str
    page_number: int | None


@dataclass
class StructuralChunker:
    max_tokens: int = 300
    min_tokens: int = 50

    def chunk(self, extracted: ExtractedText) -> Iterator[Chunk]:
        """Chunk the extracted text, respecting structure."""
        if extracted.source_format == "pdf":
            yield from self._chunk_pdf(extracted)
        else:
            yield from self._chunk_plain(extracted)

    def _chunk_pdf(self, extracted: ExtractedText) -> Iterator[Chunk]:
        """Chunk PDF pages, attempting table detection per page."""
        for page_idx, page_text in enumerate(extracted.pages):
            if not page_text.strip():
                continue
            page_num = page_idx + 1
            sections = self._split_sections(page_text)
            for section_title, body in sections:
                yield from self._chunk_section(body, section_title, page_num)

    def _split_sections(self, text: str) -> list[tuple[str | None, str]]:
        """Split text into (section_title, body) pairs based on heading patterns."""
        lines = text.split("\n")
        sections: list[tuple[str | None, str]] = []
        current_title: str | None = None
        current_body: list[str] = []

        for line in lines:
            stripped = line.strip()
            if self._is_heading(stripped):
                if current_body:
                    sections.append(
                        (current_title, "\n".join(current_body).strip())
                    )
                current_title = stripped
                current_body = []
            else:
                current_body.append(line)

        if current_body:
            sections.append(
                (current_title, "\n".join(current_body).strip())
            )

        return [(title, body) for title, body in sections if body.strip()]

    def _is_heading(self, line: str) -> bool:
        """Detect heading lines."""
        if len(line) <= 80 and len(line.split()) <= 12:
            if line.isupper() or line.endswith(":") or line.endswith("—"):
                return True
            if line.startswith("§") or line.startswith("Section"):
                return True
        return False

    def _chunk_section(
        self, body: str, section: str | None, page_num: int | None
    ) -> Iterator[Chunk]:
        """Split a section body into chunks, preserving tables and checklists."""
        paragraphs = body.split("\n")
        current: list[str] = []

        for para in paragraphs:
            if not para.strip():
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                continue

            # Check for specialized chunk types
            table_yielded = list(chunk_table(para, section=section, page_number=page_num))
            if table_yielded:
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                for tc in table_yielded:
                    yield Chunk(
                        content=tc.content,
                        section=tc.section,
                        chunk_type=tc.chunk_type,
                        page_number=tc.page_number,
                    )
                continue

            checklist_yielded = list(chunk_checklist(para, section=section, page_number=page_num))
            if checklist_yielded:
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                for cc in checklist_yielded:
                    yield Chunk(
                        content=cc.content,
                        section=cc.section,
                        chunk_type=cc.chunk_type,
                        page_number=cc.page_number,
                    )
                continue

            # Fallback: use inline table detection for whitespace-separated tables
            if self._is_table_block(para):
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                yield Chunk(
                    content=para,
                    section=section,
                    chunk_type="table",
                    page_number=page_num,
                )
                continue

            current.append(para)
            if self._count_tokens("\n".join(current)) >= self.max_tokens:
                yield from self._yield_text_chunk(current, section, page_num)
                current = []

        if current:
            yield from self._yield_text_chunk(current, section, page_num)

    def _yield_text_chunk(
        self, lines: list[str], section: str | None, page_num: int | None
    ) -> Iterator[Chunk]:
        """Yield one or more text chunks from accumulated lines."""
        content = "\n".join(lines)
        if self._count_tokens(content) <= self.max_tokens:
            yield Chunk(
                content=content,
                section=section,
                chunk_type="paragraph",
                page_number=page_num,
            )
        else:
            yield from self._chunk_text_block(content, section, page_num)

    def _chunk_plain(self, extracted: ExtractedText) -> Iterator[Chunk]:
        """Chunk plain text content (txt, md, docx, html).

        Splits on blank lines into logical blocks. Within each block,
        detects tables, checklists, and splits overly long blocks.
        """
        text = extracted.text.strip()
        if not text:
            return

        blocks = re.split(r"\n\s*\n", text)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Check for specialized chunk types
            table_chunks = list(chunk_table(block, section=None, page_number=None))
            if table_chunks:
                for tc in table_chunks:
                    yield Chunk(
                        content=tc.content,
                        section=tc.section,
                        chunk_type=tc.chunk_type,
                        page_number=tc.page_number,
                    )
                continue

            checklist_chunks = list(chunk_checklist(block, section=None, page_number=None))
            if checklist_chunks:
                for cc in checklist_chunks:
                    yield Chunk(
                        content=cc.content,
                        section=cc.section,
                        chunk_type=cc.chunk_type,
                        page_number=cc.page_number,
                    )
                continue

            if self._is_table_block(block):
                yield Chunk(
                    content=block,
                    section=None,
                    chunk_type="table",
                    page_number=None,
                )
            else:
                yield from self._chunk_text_block(block)

    def _chunk_text_block(
        self,
        block: str,
        section: str | None = None,
        page_num: int | None = None,
    ) -> Iterator[Chunk]:
        """Split a text block into chunks of reasonable size."""
        if self._count_tokens(block) <= self.max_tokens:
            yield Chunk(
                content=block,
                section=section,
                chunk_type="paragraph",
                page_number=page_num,
            )
            return

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', block)
        current: list[str] = []

        for sent in sentences:
            current.append(sent)
            if self._count_tokens("\n".join(current)) >= self.max_tokens:
                yield Chunk(
                    content="\n".join(current),
                    section=section,
                    chunk_type="paragraph",
                    page_number=page_num,
                )
                current = []

        if current:
            yield Chunk(
                content="\n".join(current),
                section=section,
                chunk_type="paragraph",
                page_number=page_num,
            )

    def _is_table_block(self, text: str) -> bool:
        """Detect table-like text blocks (2+ rows, consistent columns)."""
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return False

        first_line_cells = len(lines[0].split())
        if first_line_cells < 3:
            return False

        # Check first 3 lines have consistent column count
        consistent_count = 0
        for line in lines:
            if len(line.split()) == first_line_cells:
                consistent_count += 1

        return consistent_count >= 2

    def _count_tokens(self, text: str) -> int:
        """Approximate token count (words * 1.3)."""
        return int(len(text.split()) * 1.3)
