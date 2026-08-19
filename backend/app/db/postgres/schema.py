"""Idempotent schema initialization.

Runs `CREATE TABLE IF NOT EXISTS` statements. Safe to run on every
startup (dev default) or via `scripts/migrate_db.sh` in production.

NOTE: with DEC-4 landed (Alembic, M2), this module is the BASELINE source
of truth, not the migration tool. Migration `0001_baseline` re-runs these
exact statement lists so `alembic upgrade head` can build a fresh database
or no-op on an existing one; `ensure_schema()` remains as the dev-only
bootstrap (`ASTO_AUTO_CREATE_SCHEMA`). Every future schema change ships a
migration under `migrations/versions/` — this DDL list is frozen.
"""

from __future__ import annotations

import psycopg

from app.db.postgres import session

DDL_STATEMENTS: list[str] = [
    # --- Users (staff) ---
    """
    CREATE TABLE IF NOT EXISTS users (
        id                  BIGSERIAL PRIMARY KEY,
        email               TEXT NOT NULL UNIQUE,
        password_hash       TEXT NOT NULL,
        full_name           TEXT,
        role                TEXT NOT NULL DEFAULT 'loan_officer',
        department          TEXT NOT NULL DEFAULT 'general',
        allowed_departments TEXT[] NOT NULL DEFAULT '{}',
        is_active           BOOLEAN NOT NULL DEFAULT true,
        totp_secret         TEXT,
        totp_enabled        BOOLEAN NOT NULL DEFAULT false,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Clients (external audience) ---
    """
    CREATE TABLE IF NOT EXISTS clients (
        id            BIGSERIAL PRIMARY KEY,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        full_name     TEXT,
        is_active     BOOLEAN NOT NULL DEFAULT true,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Properties (owned by a client) ---
    """
    CREATE TABLE IF NOT EXISTS properties (
        id            BIGSERIAL PRIMARY KEY,
        client_id     BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        address       TEXT,
        city          TEXT,
        state         TEXT,
        postal_code   TEXT,
        property_type TEXT,
        is_active     BOOLEAN NOT NULL DEFAULT true,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Cases (mortgages / active matters, owned by a client) ---
    """
    CREATE TABLE IF NOT EXISTS cases (
        id           BIGSERIAL PRIMARY KEY,
        case_number  TEXT NOT NULL UNIQUE,
        client_id    BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        property_id  BIGINT REFERENCES properties(id) ON DELETE SET NULL,
        loan_amount  NUMERIC(14, 2),
        status       TEXT NOT NULL DEFAULT 'active',
        is_active    BOOLEAN NOT NULL DEFAULT true,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Staff â†” client assignments (scopes staff search to assigned clients) ---
    """
    CREATE TABLE IF NOT EXISTS staff_client_assignments (
        user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_id   BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, client_id)
    )
    """,
    # --- Documents ---
    """
    CREATE TABLE IF NOT EXISTS documents (
        id              BIGSERIAL PRIMARY KEY,
        title           TEXT NOT NULL,
        source_path     TEXT,
        doc_type        TEXT NOT NULL DEFAULT 'policy',
        department      TEXT NOT NULL DEFAULT 'general',
        client_id       BIGINT REFERENCES clients(id),
        property_id     BIGINT REFERENCES properties(id),
        uploaded_by     BIGINT REFERENCES users(id),
        approval_status TEXT NOT NULL DEFAULT 'approved'
                         CHECK (approval_status IN ('pending','approved','rejected')),
        approved_by     BIGINT REFERENCES users(id),
        approved_at     TIMESTAMPTZ,
        is_active       BOOLEAN NOT NULL DEFAULT true,
        is_approved     BOOLEAN NOT NULL DEFAULT true,
        version         INTEGER NOT NULL DEFAULT 1,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Document chunks (the searchable unit) ---
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        id              BIGSERIAL PRIMARY KEY,
        document_id     BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        content         TEXT NOT NULL,
        content_hash    TEXT NOT NULL UNIQUE,
        embedding       vector(384),
        section         TEXT,
        chunk_type      TEXT NOT NULL DEFAULT 'paragraph',
        department      TEXT NOT NULL DEFAULT 'general',
        approval_status TEXT NOT NULL DEFAULT 'approved'
                         CHECK (approval_status IN ('pending','approved','rejected')),
        approved_by     BIGINT REFERENCES users(id),
        approved_at     TIMESTAMPTZ,
        is_active       BOOLEAN NOT NULL DEFAULT true,
        is_approved     BOOLEAN NOT NULL DEFAULT true,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        fts             tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    )
    """,
    # --- Audit log (every query, immutable, compliance artifact) ---
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id            BIGSERIAL PRIMARY KEY,
        user_id       BIGINT,
        audience      TEXT,
        query         TEXT NOT NULL,
        sub_queries   JSONB,
        retrieved_ids BIGINT[],
        confidence    DOUBLE PRECISION,
        response_id   TEXT,
        outcome       TEXT,
        latency_ms    DOUBLE PRECISION,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Feedback ---
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT,
        response_id TEXT NOT NULL,
        rating      SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
        comment     TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Feature flags (M8: ship half-built features safely) ---
    """
    CREATE TABLE IF NOT EXISTS feature_flags (
        name       TEXT PRIMARY KEY,
        enabled    BOOLEAN NOT NULL DEFAULT true,
        department TEXT NOT NULL DEFAULT 'general',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Query synonyms (J8: pre-query expansion, admin-managed) ---
    """
    CREATE TABLE IF NOT EXISTS synonyms (
        id        BIGSERIAL PRIMARY KEY,
        canonical TEXT NOT NULL,
        alias     TEXT NOT NULL,
        UNIQUE (canonical, alias)
    )
    """,
    # --- Knowledge gaps (low-confidence / no-answer signals) ---
    """
    CREATE TABLE IF NOT EXISTS knowledge_gaps (
        id         BIGSERIAL PRIMARY KEY,
        query      TEXT NOT NULL,
        intent     TEXT,
        confidence DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Document approval trail (who/when approved or rejected) ---
    """
    CREATE TABLE IF NOT EXISTS approval_log (
        id             BIGSERIAL PRIMARY KEY,
        document_id    BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        reviewed_by    BIGINT REFERENCES users(id),
        from_status    TEXT,
        to_status      TEXT NOT NULL CHECK (to_status IN ('pending','approved','rejected')),
        reason         TEXT,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Case status events (client-facing status timeline) ---
    """
    CREATE TABLE IF NOT EXISTS case_events (
        id         BIGSERIAL PRIMARY KEY,
        case_id    BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        status     TEXT NOT NULL,
        note       TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- SOPs (official Standard Operating Procedures, department-scoped) ---
    """
    CREATE TABLE IF NOT EXISTS sops (
        id          BIGSERIAL PRIMARY KEY,
        title       TEXT NOT NULL,
        department  TEXT NOT NULL DEFAULT 'general',
        body        TEXT NOT NULL,
        version     INTEGER NOT NULL DEFAULT 1,
        created_by  BIGINT REFERENCES users(id),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        is_active   BOOLEAN NOT NULL DEFAULT true
    )
    """,
    # --- SOP access requests (staff request create/edit rights) ---
    """
    CREATE TABLE IF NOT EXISTS sop_access_requests (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        action      TEXT NOT NULL CHECK (action IN ('create','edit')),
        department  TEXT NOT NULL,
        reason      TEXT,
        status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected')),
        reviewed_by BIGINT REFERENCES users(id),
        reviewed_at TIMESTAMPTZ,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Workflows (active operational workflows, department-scoped) ---
    """
    CREATE TABLE IF NOT EXISTS workflows (
        id          BIGSERIAL PRIMARY KEY,
        title       TEXT NOT NULL,
        department  TEXT NOT NULL DEFAULT 'general',
        case_id     BIGINT REFERENCES cases(id) ON DELETE SET NULL,
        status      TEXT NOT NULL DEFAULT 'in_progress'
                    CHECK (status IN ('in_progress','review','done')),
        assigned_to BIGINT REFERENCES users(id),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Case notes (staff collaboration on a client's case) ---
    """
    CREATE TABLE IF NOT EXISTS case_notes (
        id         BIGSERIAL PRIMARY KEY,
        case_id    BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body       TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Conversations (client<->staff messaging, Phase F6) ---
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id         BIGSERIAL PRIMARY KEY,
        case_id    BIGINT REFERENCES cases(id) ON DELETE SET NULL,
        client_id  BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        subject    TEXT NOT NULL DEFAULT 'General',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Messages within a conversation (Phase F6) ---
    """
    CREATE TABLE IF NOT EXISTS messages (
        id              BIGSERIAL PRIMARY KEY,
        conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        sender_type     TEXT NOT NULL CHECK (sender_type IN ('staff', 'client')),
        sender_user_id  BIGINT REFERENCES users(id) ON DELETE SET NULL,
        sender_client_id BIGINT REFERENCES clients(id) ON DELETE SET NULL,
        body            TEXT NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Notifications (generic, Phase G0) ---
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id         BIGSERIAL PRIMARY KEY,
        user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type       TEXT NOT NULL DEFAULT 'info',
        title      TEXT NOT NULL,
        body       TEXT,
        link       TEXT,
        is_read    BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Refresh tokens (H1: HttpOnly rotating session cookie) ---
    # Only the SHA-256 hash of each refresh token is stored, so a DB leak
    # never exposes a usable credential. user_id XOR client_id is set per
    # audience; audience is validated on read. Rows are soft-revoked for
    # logout / rotation / logout-all (H5).
    """
    CREATE TABLE IF NOT EXISTS refresh_tokens (
        id         BIGSERIAL PRIMARY KEY,
        token_hash TEXT        NOT NULL UNIQUE,
        user_id    BIGINT      REFERENCES users(id) ON DELETE CASCADE,
        client_id  BIGINT      REFERENCES clients(id) ON DELETE CASCADE,
        audience   TEXT        NOT NULL CHECK (audience IN ('staff','client')),
        expires_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Password resets (H2: forgot-password flow) ---
    # One-time, short-lived (1h) reset tokens; only the hash is stored.
    # identity_id targets users XOR clients depending on audience.
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        id          BIGSERIAL PRIMARY KEY,
        email       TEXT        NOT NULL,
        audience    TEXT        NOT NULL CHECK (audience IN ('staff','client')),
        identity_id BIGINT      NOT NULL,
        token_hash  TEXT        NOT NULL UNIQUE,
        expires_at  TIMESTAMPTZ NOT NULL,
        used_at     TIMESTAMPTZ,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Login attempts (H3: brute-force throttle) ---
    # Per-email + per-IP evidence for the 5-failure/15m lockout. Rows are
    # pruned past 24h inside the same transaction that counts them. On a
    # successful login the email's failure rows are deleted (counter reset).
    """
    CREATE TABLE IF NOT EXISTS login_attempts (
        id           BIGSERIAL PRIMARY KEY,
        email        TEXT        NOT NULL,
        ip           TEXT        NOT NULL DEFAULT '',
        attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        success      BOOLEAN     NOT NULL DEFAULT false
    )
    """,
    # --- Revoked access-token jtis (H5: emergency access-token kill) ---
    # Access JWTs carry a unique jti so a single leaked token can be killed
    # immediately without waiting for expiry (POST /auth/logout-all records
    # the caller's jti; /auth/verify refuses revoked jtis). The documented
    # trade-off: admin session-kill revokes the refresh rows (no new access
    # tokens) but already-issued access JWTs stay valid until expiry unless
    # their jti is individually revoked here.
"""
    CREATE TABLE IF NOT EXISTS revoked_jtis (
        jti         TEXT        PRIMARY KEY,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Workflow definitions (L4: config-driven) ---
    """
    CREATE TABLE IF NOT EXISTS workflow_definitions (
        id          BIGSERIAL PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT,
        stages      JSONB NOT NULL DEFAULT '[]'::jsonb,
        transitions JSONB NOT NULL DEFAULT '[]'::jsonb,
        is_active   BOOL NOT NULL DEFAULT true,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Case document requirements (K1: Document checklist) ---
    """
    CREATE TABLE IF NOT EXISTS case_document_requirements (
        id              BIGSERIAL PRIMARY KEY,
        case_id         BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        name            TEXT NOT NULL,
        description     TEXT,
        required_from   TEXT NOT NULL DEFAULT 'upload',
        status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('required','pending','received','approved')),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Signature requests (K5: E-sign / document request) ---
    """
    CREATE TABLE IF NOT EXISTS signature_requests (
        id              BIGSERIAL PRIMARY KEY,
        case_id         BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        document_id     BIGINT REFERENCES documents(id) ON DELETE SET NULL,
        requested_from  TEXT NOT NULL,
        token           TEXT NOT NULL UNIQUE,
        signed_name     TEXT,
        consent         BOOLEAN NOT NULL DEFAULT false,
        signed_at       TIMESTAMPTZ,
        status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','signed','cancelled')),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Tasks (L2: Task assignment to teammates) ---
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id              BIGSERIAL PRIMARY KEY,
        case_id         BIGINT REFERENCES cases(id) ON DELETE SET NULL,
        title           TEXT NOT NULL,
        description     TEXT,
        assignee_id     BIGINT REFERENCES users(id),
        due_at          TIMESTAMPTZ,
        status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','assigned','in_progress','completed','overdue')),
        created_by      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Feature flags (M8: Safe ship-half-built features) ---
    """
    CREATE TABLE IF NOT EXISTS feature_flags (
        name            TEXT PRIMARY KEY,
        enabled         BOOLEAN NOT NULL DEFAULT true,
        department      TEXT NOT NULL DEFAULT 'general',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Saved searches (J7: Saved searches / search history) ---
    """
    CREATE TABLE IF NOT EXISTS saved_searches (
        id              BIGSERIAL PRIMARY KEY,
        user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        query           TEXT NOT NULL,
        filters         JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Message templates (L5: staff CRUD) ---
    """
    CREATE TABLE IF NOT EXISTS message_templates (
        id          BIGSERIAL PRIMARY KEY,
        name        TEXT NOT NULL,
        body        TEXT NOT NULL,
        department  TEXT NOT NULL DEFAULT 'general',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Appointments (L6: calendar / stretch) ---
    """
    CREATE TABLE IF NOT EXISTS appointments (
        id          BIGSERIAL PRIMARY KEY,
        title       TEXT NOT NULL,
        description TEXT,
        start_at    TIMESTAMPTZ NOT NULL,
        end_at      TIMESTAMPTZ NOT NULL,
        department  TEXT NOT NULL DEFAULT 'general',
        staff_id    BIGINT REFERENCES users(id),
        status      TEXT NOT NULL DEFAULT 'scheduled'
                    CHECK (status IN ('scheduled', 'completed', 'cancelled')),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]

# Idempotent column additions for schemas created before the dual-audience
# model existed (CREATE TABLE IF NOT EXISTS cannot alter an existing table).
ALTER_STATEMENTS: list[str] = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS client_id BIGINT REFERENCES clients(id)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS property_id BIGINT REFERENCES properties(id)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by BIGINT REFERENCES users(id)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'approved'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approved_by BIGINT REFERENCES users(id)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'approved'",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS approved_by BIGINT REFERENCES users(id)",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS notification_prefs JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS metadata JSONB",
    # audit_log.audience: added alongside the dual-audience scoping feature.
    # Fresh databases get it via the CREATE TABLE above; databases that
    # already ran an earlier ensure_schema()/baseline without it need this.
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS audience TEXT",
]

# CHECK constraints added via ALTER (no IF NOT EXISTS for constraints in PG,
# so guard with a DO block â€” idempotent across restarts).
CONSTRAINT_STATEMENTS: list[str] = [
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_documents_approval_status') THEN
            ALTER TABLE documents ADD CONSTRAINT chk_documents_approval_status
                CHECK (approval_status IN ('pending','approved','rejected'));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_chunks_approval_status') THEN
            ALTER TABLE document_chunks ADD CONSTRAINT chk_chunks_approval_status
                CHECK (approval_status IN ('pending','approved','rejected'));
        END IF;
    END $$;
    """,
]

INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_active ON document_chunks (department, is_active, is_approved)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_fts ON document_chunks USING gin (fts)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_content_hash ON document_chunks (content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_documents_client ON documents (client_id)",
    "CREATE INDEX IF NOT EXISTS idx_documents_property ON documents (property_id)",
    "CREATE INDEX IF NOT EXISTS idx_properties_client ON properties (client_id)",
    "CREATE INDEX IF NOT EXISTS idx_cases_client ON cases (client_id)",
    "CREATE INDEX IF NOT EXISTS idx_cases_property ON cases (property_id)",
    "CREATE INDEX IF NOT EXISTS idx_staff_client_client ON staff_client_assignments (client_id)",
    "CREATE INDEX IF NOT EXISTS idx_approval_log_document ON approval_log (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_case_events_case ON case_events (case_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sops_department ON sops (department, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_sop_req_status ON sop_access_requests (status, department)",
    "CREATE INDEX IF NOT EXISTS idx_workflows_dept ON workflows (department, status)",
    "CREATE INDEX IF NOT EXISTS idx_case_notes_case ON case_notes (case_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_client ON conversations (client_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_case ON conversations (case_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id, is_read, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id, client_id, revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_password_resets_token ON password_resets (token_hash, used_at)",
    "CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts (email, attempted_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts (ip, attempted_at DESC)",
]


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for ddl in DDL_STATEMENTS:
            cur.execute(ddl)
        for alter in ALTER_STATEMENTS:
            cur.execute(alter)
        for constraint in CONSTRAINT_STATEMENTS:
            cur.execute(constraint)
        for idx in INDEX_STATEMENTS:
            cur.execute(idx)
    conn.commit()


def ensure_schema() -> None:
    """Idempotent; safe to call at app startup."""
    with session.acquire() as conn:
        init_schema(conn)
