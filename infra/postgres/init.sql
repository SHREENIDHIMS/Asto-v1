CREATE EXTENSION IF NOT EXISTS vector;

-- Scratch database for the integration test suite (ASTO_TEST_DATABASE_URL).
-- Lives inside the SAME shared Postgres instance — never a second container
-- (CLAUDE.md rule 2). Tests seed + clear benchmark rows and must not touch
-- the dev asto_assistant data. Must carry the vector extension too, because
-- the connection layer (session.acquire -> register_vector) requires it
-- before any schema init runs.
--
-- NOTE: docker-entrypoint-initdb.d only runs on a fresh data volume. For an
-- already-initialized volume (created before this line), create it once:
--   docker compose exec postgres psql -U asto_app -c "CREATE DATABASE asto_test"
--   docker compose exec postgres psql -U asto_app -d asto_test -c "CREATE EXTENSION IF NOT EXISTS vector"
CREATE DATABASE asto_test;

\connect asto_test
CREATE EXTENSION IF NOT EXISTS vector;
