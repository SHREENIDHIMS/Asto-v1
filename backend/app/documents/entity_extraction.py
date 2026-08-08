"""Dictionary-based entity extraction for document ingestion.

Unlike query-time entity extraction (which must be lightweight), the
batch ingestion pipeline can afford a slightly richer dictionary pass
to tag chunks with domain entities for later faceting/filtering.

Entities are extracted using keyword and pattern matching against the
domain vocabulary — no spaCy or GLiNER, keeping memory usage flat.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.query_processing.domain_terms import DOMAIN_TERMS


@dataclass
class IngestionEntities:
    lenders: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    property_types: list[str] = field(default_factory=list)
    acronyms: list[str] = field(default_factory=list)


def extract_entities(text: str) -> IngestionEntities:
    """Extract domain entities from text using dictionary matching."""
    entities = IngestionEntities()
    lowered = text.lower()

    for canonical, meta in DOMAIN_TERMS.items():
        entity_type = meta["type"]
        if entity_type not in ("acronym", "abbreviation", "lender", "product", "document", "property"):
            continue
        for alias in meta["aliases"]:
            if alias in lowered:
                if entity_type in ("acronym", "abbreviation"):
                    if canonical not in entities.acronyms:
                        entities.acronyms.append(canonical)
                elif entity_type == "lender":
                    if canonical not in entities.lenders:
                        entities.lenders.append(canonical)
                elif entity_type == "product":
                    if canonical not in entities.products:
                        entities.products.append(canonical)
                elif entity_type == "document":
                    if canonical not in entities.documents:
                        entities.documents.append(canonical)
                elif entity_type == "property":
                    if canonical not in entities.property_types:
                        entities.property_types.append(canonical)
                break

    return entities
