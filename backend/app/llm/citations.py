"""Cite-with-LLM mode (DEC-1 seam; OFF by default).

DEC-1 is closed as "No" for now: the request-serving path never calls an
LLM and every answer stays verbatim from a source. This module is the
*ready hook* — a single call site in the document search path
(``app/api/v1/search.py``) that:

- returns the :class:`~app.response.package_builder.ResponsePackage`
  **unchanged** while ``settings.llm_enabled`` is false (the current
  default — zero latency, zero behavior change), and
- would, if a future decision flips ``ASTO_LLM_ENABLED``, synthesize an
  answer from the retrieved excerpts through the hosted API
  (``app/llm/provider.py``) with per-sentence citations mapped back to
  source documents.

The provider, prompt builder, and response parser are real and unit-tested
so that flipping the flag needs no new plumbing. Note: enabling it sends
retrieved excerpts to the configured provider — the compliance trade-off
DEC-1 documented.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.llm.provider import LLMClient, LLMConfig, LLMError
from app.response.package_builder import ResponsePackage

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """One synthesized sentence plus the document(s) it cites."""

    sentence: str
    document_ids: list[int]
    titles: list[str] = field(default_factory=list)


@dataclass
class CitationResult:
    answer: str
    citations: list[Citation] = field(default_factory=list)


_SYSTEM_PROMPT = (
    "You are a citation assistant for a loan-origination knowledge base. "
    "Synthesize a concise answer to the user's question using ONLY the "
    "provided excerpts. End every sentence with its source references as "
    "[n] where n is the excerpt index. Never invent facts; if the excerpts "
    "do not support an answer, say so and cite nothing."
)


def build_citation_prompt(package: ResponsePackage, query_text: str) -> str:
    """Format retrieved excerpts into the user prompt with [n] indices."""
    parts = [f"QUESTION: {query_text}", ""]
    for i, excerpt in enumerate(package.excerpts, start=1):
        parts.append(f"[{i}] {excerpt.source.title} :: {excerpt.text}")
    return "\n".join(parts)


_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?](?:\s*\[\d+\])*)+")


def parse_citation_answer(
    text: str, excerpt_titles: list[str]
) -> CitationResult:
    """Split the model output into sentences with their [n] citations."""
    result = CitationResult(answer=text.strip())
    # A sentence is content ending in punctuation, with any space-separated
    # [n] markers kept attached ("Alpha. [1]" stays one sentence).
    for match in _SENTENCE_RE.finditer(text.strip()):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        indices = sorted(
            {int(n) for n in re.findall(r"\[(\d+)\]", sentence)}
        )
        if not indices:
            continue
        ids = []
        titles = []
        for idx in indices:
            if 1 <= idx <= len(excerpt_titles):
                ids.append(idx)
                titles.append(excerpt_titles[idx - 1])
        result.citations.append(
            Citation(sentence=sentence, document_ids=ids, titles=titles)
        )
    return result


def _run_citation_mode(package: ResponsePackage, query_text: str) -> ResponsePackage:
    """The future DEC-1 path: synthesize + cite via the hosted API."""
    if not settings.llm_provider_url:
        logger.warning("llm_enabled is true but llm_provider_url is empty — skipping cite mode")
        return package
    client = LLMClient(LLMConfig(
        base_url=settings.llm_provider_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    ))
    prompt = build_citation_prompt(package, query_text)
    try:
        text = client.chat(_SYSTEM_PROMPT, prompt)
    except LLMError as exc:
        logger.error("cite-with-LLM mode failed: %s", exc)
        return package
    excerpt_titles = [e.source.title for e in package.excerpts]
    result = parse_citation_answer(text, excerpt_titles)
    if result.answer:
        package.answer = result.answer
    package.citations = [
        {
            "sentence": c.sentence,
            "sources": [{"document": t} for t in c.titles],
        }
        for c in result.citations
    ]
    return package


def maybe_apply_citation_mode(
    package: ResponsePackage, query_text: str
) -> ResponsePackage:
    """Hook into the document search path. No-op while LLM mode is OFF.

    This is the sole call site a future DEC-1 flip needs; while
    ``settings.llm_enabled`` is false the package is returned unchanged and
    nothing is sent anywhere.
    """
    if not settings.llm_enabled:
        return package
    return _run_citation_mode(package, query_text)