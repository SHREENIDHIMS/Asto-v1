-- Runs once, on first container start, via docker-entrypoint-initdb.d.
-- Add one file like this per project — each project gets its own
-- database inside the ONE shared Postgres instance, not its own
-- Postgres process.
--
-- The application role password is read from the environment so it is
-- never committed to the repo. It is supplied via docker-compose env
-- (POSTGRES_APP_PASSWORD) at container initialization time. The role
-- is created with the password set later by the app's own provisioning
-- step (scripts/migrate_db.sh) if this file is used as-is; see
-- backend/.env.example for the required ASTO_DB_PASSWORD.

CREATE DATABASE asto_assistant;

\connect asto_assistant

CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector, replaces Qdrant

-- Application role is created with a placeholder and its password must
-- be set explicitly at provisioning time:
CREATE ROLE asto_app LOGIN;
GRANT ALL PRIVILEGES ON DATABASE asto_assistant TO asto_app;
GRANT ALL PRIVILEGES ON SCHEMA public TO asto_app;
