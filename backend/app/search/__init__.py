"""Search package: hybrid BM25 + pgvector retrieval.

RBAC and active-version filtering happen IN the SQL WHERE clause
(CLAUDE.md rule #1), not as a post-hoc check.
"""

from app.search.hybrid_orchestrator import SearchResult, search_knowledge_base
from app.search.metadata_filters import get_search_filter

__all__ = ["search_knowledge_base", "SearchResult", "get_search_filter"]
