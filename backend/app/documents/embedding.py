"""Embedding generation for document ingestion.

Uses FastEmbed (bge-small-en-v1.5 ONNX Int8, ~66MB) to generate
384-dimensional embeddings. Loaded lazily at first use and cached.

Per CLAUDE.md rule 5: this module runs ONLY in the batch ingestion
process — never imported by app.main.py or any request handler.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

logger = logging.getLogger(__name__)

try:
    from fastembed import TextEmbedding

    _HAS_FASTEMBED = True
except ImportError:
    _HAS_FASTEMBED = False
    logger.warning("fastembed not installed; embedding generation disabled")


@lru_cache(maxsize=1)
def _get_model() -> TextEmbedding:
    """Lazily load and cache the FastEmbed model."""
    if not _HAS_FASTEMBED:
        raise RuntimeError("fastembed is not installed")
    from app.config import settings

    logger.info("Loading embedding model: %s", settings.embedding_model)
    model = TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
    )
    return model


def generate_embeddings(texts: Sequence[str]) -> list[list[float]]:
    """Generate embeddings for a batch of text chunks."""
    if not _HAS_FASTEMBED:
        raise RuntimeError("fastembed is not installed")

    model = _get_model()
    embeddings = list(model.embed(texts, batch_size=16))
    logger.info("Generated %d embeddings", len(embeddings))
    return embeddings
