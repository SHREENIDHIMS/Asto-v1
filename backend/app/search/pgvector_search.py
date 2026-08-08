"""pgvector semantic search: generate query embedding + cosine similarity.

Uses FastEmbed (bge-small-en-v1.5) for query-time embedding. Model is
loaded once and cached via lru_cache.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from fastembed import TextEmbedding

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_embedding_model() -> TextEmbedding:
    """Lazily load and cache the FastEmbed model."""
    logger.info("Loading embedding model: %s", settings.embedding_model)
    model = TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
    )
    return model


def embed_query(text: str) -> list[float]:
    """Generate a 384-dim embedding for a query string."""
    model = _get_embedding_model()
    embeddings = list(model.embed([text]))
    return embeddings[0]
