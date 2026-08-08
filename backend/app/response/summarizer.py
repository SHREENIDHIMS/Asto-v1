"""Extractive summarization of retrieved excerpts.

Uses Sumy TextRank to select the most salient sentences verbatim from the
top retrieved excerpts. No abstractive synthesis — every returned sentence
exists verbatim in a source excerpt and carries its source citation.

A self-contained tokenizer is used instead of Sumy's default (which
requires an NLTK model download), keeping the runtime dependency-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sumy.nlp.stemmers import Stemmer
from sumy.parsers.plaintext import PlaintextParser
from sumy.summarizers.text_rank import TextRankSummarizer
from sumy.utils import get_stop_words

if TYPE_CHECKING:
    from app.response.package_builder import Excerpt

DEFAULT_SENTENCES = 4
_LANGUAGE = "english"

_SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]*", re.UNICODE)
_WORD_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|['-])*$", re.UNICODE)


class _RegexTokenizer:
    """Minimal tokenizer implementing Sumy's interface without NLTK."""

    def __init__(self, language: str):
        self._language = language

    @property
    def language(self):
        return self._language

    def to_sentences(self, paragraph: str):
        return tuple(
            s.strip() for s in _SENTENCE_RE.findall(paragraph) if s.strip()
        )

    def to_words(self, sentence: str):
        return tuple(w for w in sentence.split() if _WORD_RE.match(w))


@dataclass
class SummarySentence:
    """One verbatim sentence selected from a source excerpt."""

    text: str
    source_title: str
    source_section: str | None = None
    chunk_type: str = "paragraph"
    document_id: int | None = None
    chunk_id: int | None = None


def _normalize(text: str) -> str:
    """Collapse whitespace + lowercase for verbatim-matching."""

    return " ".join(text.split()).lower()


def _find_source_excerpt(
    sentence: str,
    excerpts: list[Excerpt],
) -> Excerpt | None:
    """Find the excerpt containing a sentence (verbatim match)."""

    needle = _normalize(sentence)
    for excerpt in excerpts:
        if needle and needle in _normalize(excerpt.text):
            return excerpt
    return None


def summarize_excerpts(
    excerpts: list[Excerpt],
    sentences_count: int = DEFAULT_SENTENCES,
) -> list[SummarySentence]:
    """Select the most salient sentences from the top excerpts.

    Concatenates the excerpt texts, runs Sumy TextRank, and maps each
    selected sentence back to the excerpt it came from so the summary
    keeps its citations. Returns an empty list on any failure (summary is
    best-effort and must never break the search response).
    """
    if not excerpts:
        return []

    corpus = "\n\n".join(e.text for e in excerpts)

    try:
        parser = PlaintextParser.from_string(
            corpus,
            _RegexTokenizer(_LANGUAGE),
        )
        summarizer = TextRankSummarizer(Stemmer(_LANGUAGE))
        summarizer.stop_words = get_stop_words(_LANGUAGE)
        sentences = summarizer(parser.document, sentences_count)
    except Exception:
        return []

    summary: list[SummarySentence] = []
    for sentence in sentences:
        text = str(sentence).strip()
        if not text:
            continue
        excerpt = _find_source_excerpt(text, excerpts)
        if excerpt is None:
            continue
        summary.append(SummarySentence(
            text=text,
            source_title=excerpt.source.title,
            source_section=excerpt.source.section,
            chunk_type=excerpt.source.chunk_type,
            document_id=excerpt.source.document_id,
            chunk_id=excerpt.source.chunk_id,
        ))

    return summary
