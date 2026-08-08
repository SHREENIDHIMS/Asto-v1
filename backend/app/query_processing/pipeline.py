"""Query processing pipeline.

``process_query(raw) -> QueryPlan`` is a pure function (no DB, no I/O)
that turns a raw user message into one or more structured sub-queries:

    raw -> normalize -> multi-question split
        -> per sub-query: spell-correct -> entity extraction
                         -> intent -> expansion

Everything here is deterministic and dependency-free (rapidfuzz aside),
so it is cheap to run at query time on the shared host and trivial to
unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.query_processing import entity_extraction as ent
from app.query_processing import intent_detection, multi_question, normalization
from app.query_processing import query_expansion as qexpand
from app.query_processing import spell_correction


@dataclass
class StructuredQuery:
    display: str                     # normalized sub-query (echoed to user)
    text: str                        # cleaned for search (punctuation stripped)
    expanded: str                    # expanded text fed to BM25 + embedding
    entities: list[ent.Entity] = field(default_factory=list)
    intent: str = "general"
    tokens: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    raw: str
    normalized: str
    sub_queries: list[StructuredQuery]
    truncated: bool = False


def _build_sub_query(sub: str) -> StructuredQuery:
    corrected = spell_correction.correct(sub)
    display = corrected.strip(" ?!;,")
    text = normalization.clean_for_search(display)
    entities = ent.extract_entities(text)
    expanded = qexpand.expand(text, entities)
    intent = intent_detection.detect_intent(text, entities)
    tokens = text.split()
    return StructuredQuery(
        display=display,
        text=text,
        expanded=expanded,
        entities=entities,
        intent=intent,
        tokens=tokens,
    )


def process_query(raw: str) -> QueryPlan:
    normalized = normalization.normalize(raw)
    subs, truncated = multi_question.plan_split(normalized)
    structured = [_build_sub_query(s) for s in subs]
    return QueryPlan(raw=raw, normalized=normalized, sub_queries=structured, truncated=truncated)


def has_searchable_content(plan: QueryPlan) -> bool:
    return any(sq.text for sq in plan.sub_queries)
