"""Application configuration.

Reads settings from environment variables with the ASTO_ prefix
(e.g. ASTO_DATABASE_URL), plus an optional .env file. All values are
plain configuration with documented defaults; ranking weights and
confidence thresholds deliberately live in their own modules
(ranking/weights_config.py, response/confidence_thresholds.py) so any
change to them has to pass the evaluation benchmark gate first
(CLAUDE.md rule 7).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASTO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    app_name: str = "Asto"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- Database ---
    # postgresql://user:password@host:port/dbname
    database_url: str = "postgresql://asto_app:devpass@127.0.0.1:5433/asto_assistant"
    # Scratch database for the test suite (see backend/tests/conftest.py).
    # Integration tests seed + clear benchmark rows and must never touch a
    # developer's real database by accident.
    test_database_url: str | None = None
    database_pool_max: int = 4
    database_pool_timeout_s: int = 30

    # --- Auth ---
    jwt_secret: str = ""  # required via ASTO_JWT_SECRET env var; no default for safety
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480

    # --- CORS ---
    # Comma-separated list of allowed origins; "*" in non-production only.
    cors_origins: str = "*"

    # --- Embeddings (query-time, always-on process) ---
    embedding_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "nlp_models/embeddings"
    embedding_dim: int = 384

    # --- Storage ---
    storage_pending_dir: str = "storage/pending"
    storage_processed_dir: str = "storage/processed"
    max_upload_bytes: int = 20 * 1024 * 1024

    # --- Search ---
    bm25_limit: int = 25
    vector_limit: int = 25
    max_sub_queries: int = 4

    # --- Response ---
    max_excerpt_chars: int = 600
    max_evidence_docs: int = 5

    # --- Behavioural ---
    auto_create_schema: bool = True
    audit_enabled: bool = True

    # --- Optional reranker (P2; OFF by default on the micro tier) ---
    rerank_enabled: bool = False
    rerank_model_dir: str = "nlp_models/reranker"

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        if not self.jwt_secret:
            if self.environment == "development":
                # Allow empty secret only in development — tests use env vars
                return self
            raise ValueError(
                "ASTO_JWT_SECRET must be set when environment is not 'development'"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
