#!/usr/bin/env bash
set -euo pipefail

# Seed the database with initial schema + users.
# Run this against the shared Postgres instance.

cd /opt/projects/asto/backend
source .venv/bin/activate 2>/dev/null || true

echo "Creating schema..."
python -m app.db.postgres.schema

echo "Seeding users..."
python -m scripts.seed_db

echo "Done."