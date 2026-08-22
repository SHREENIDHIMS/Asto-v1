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
    # HttpOnly refresh-token cookie (H1). The access JWT lives in memory on
    # the client only; this cookie is the long-lived session credential,
    # rotated on every use and validated against hashes in refresh_tokens.
    refresh_token_ttl_days: int = 30
    auth_cookie_name: str = "asto_refresh"
    auth_cookie_secure: bool = False  # set ASTO_AUTH_COOKIE_SECURE=true behind TLS
    auth_cookie_samesite: str = "lax"
    # Reset-password links point at this UI (H2). When DEC-3's SMTP decides,
    # delivery moves from the log fallback to a real email transport.
    password_reset_ttl_hours: int = 1
    # Origin used to build emailed links (reset links today, more mail later).
    frontend_url: str = "http://localhost:3011"
    # --- Email (DEC-3: generic SMTP + console fallback) ---
    # Any SMTP relay works (Postfix, SES SMTP, SendGrid, Mailgun, ...).
    # When smtp_host is empty the mailer falls back to logging messages at
    # INFO — every delivery seam still works in local dev with no provider.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # e.g. "Asto <no-reply@example.com>"; falls back to no-reply@asto.local
    smtp_use_tls: bool = True   # STARTTLS on 587
    smtp_use_ssl: bool = False  # implicit TLS on 465
    # --- Login throttle (H3, brute-force protection) ---
    # A login attempt that fails when >=max_failures failures are recorded for
    # the email (or >=max_ip_failures for the client IP) inside the lockout
    # window is rejected with 429. Evidence is pruned past prune_hours.
    login_max_failures: int = 5
    login_max_ip_failures: int = 10
    login_lockout_minutes: int = 15
    login_attempt_prune_hours: int = 24

    # --- Admin 2FA (H4, TOTP) ---
    # Short-lived, single-use token issued by /auth/login when the account
    # has 2FA enabled; POST /auth/2fa swaps it for the real JWT.
    two_fa_token_ttl_minutes: int = 5

    # --- CORS ---
    # Comma-separated list of allowed origins. Credentialed requests (H1
    # cookies) require an explicit origin, so the dev default is the local
    # frontend origin rather than "*" (browsers reject "*" + credentials).
    cors_origins: str = "http://localhost:3011,http://127.0.0.1:3011"

    # --- Embeddings (query-time, always-on process) ---
    embedding_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "nlp_models/embeddings"
    embedding_dim: int = 384

    # --- Storage ---
    storage_pending_dir: str = "storage/pending"
    storage_processed_dir: str = "storage/processed"
    max_upload_bytes: int = 20 * 1024 * 1024

    # --- Watermarking (I5, hardened per audit #13) ---
    # Files above this size skip request-time watermarking (served as an
    # audited attachment instead) so pypdf/PIL can't blow the worker's
    # memory cap on a huge document. Watermarked output is cached on disk
    # per (document, version, viewer, day) in storage/watermark_cache.
    watermark_max_bytes: int = 20 * 1024 * 1024
    storage_watermark_cache_dir: str = "storage/watermark_cache"

    # --- Backups (M6) ---
    # Rotating pg_dump destination + how many dumps to keep. Set
    # ASTO_PGDUMP_COMMAND / ASTO_PGRESTORE_COMMAND if pg_dump/pg_restore
    # aren't on PATH (e.g. docker compose exec -T postgres pg_dump).
    backup_dir: str = "storage/backups"
    backup_keep: int = 7

    # --- Search ---
    bm25_limit: int = 25
    vector_limit: int = 25
    max_sub_queries: int = 4
    max_query_length: int = 1000  # reject oversized search payloads (DoS guard)

    # --- Response ---
    max_excerpt_chars: int = 600
    max_evidence_docs: int = 5

    # --- Behavioural ---
    auto_create_schema: bool = True
    audit_enabled: bool = True

    # --- Optional reranker (P2; OFF by default on the micro tier) ---
    rerank_enabled: bool = False
    rerank_model_dir: str = "nlp_models/reranker"

    # --- Hosted LLM seam (DEC-1; OFF by default) ---
    # DEC-1 is closed as "No" today: the request-serving path never calls an
    # LLM and every answer stays verbatim from a source. This block makes the
    # hosted-API path *ready* so a future flip of ``llm_enabled`` activates
    # it (see app/llm/). The provider URL is OpenAI-compatible
    # (/chat/completions): OpenAI, Anthropic-via-gateway, Azure, a self-hosted
    # vLLM, etc. all speak it.
    llm_enabled: bool = False  # master switch — must stay false until DEC-1 is revisited
    llm_provider_url: str = ""  # e.g. https://api.openai.com/v1
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 30
    llm_max_tokens: int = 500
    llm_temperature: float = 0.2

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        # A short or empty secret is forgeable and the guard must not depend on
        # the environment being "production" (deploys can silently default to
        # development). Require a strong secret in every environment; no
        # default is provided. Tests/CI set ASTO_JWT_SECRET explicitly.
        if len(self.jwt_secret) < 32:
            raise ValueError(
                "ASTO_JWT_SECRET must be set to a strong secret (>= 32 chars) "
                "in every environment. No default is provided for safety."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
