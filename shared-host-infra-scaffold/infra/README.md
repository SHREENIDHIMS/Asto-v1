# Shared-Host Infra Scaffold — Setup

Run once per fresh EC2 instance, in this order.

## 1. Base system prep

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
# NOTE: do NOT install system nginx. We run nginx in Docker instead —
# installing both would double-install and conflict on the listener ports.

# 2GB swap as an OOM-killer safety net (not a performance fix)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Bring up shared infra (Postgres + Nginx) — do this before any project

```bash
cd infra/shared
cp .env.example .env   # set POSTGRES_SUPERUSER_PASSWORD
docker compose up -d
docker compose ps       # confirm both containers healthy
```

Each project adds its own `postgres/init/NN_projectname.sql` file here
(creates its own database inside the one shared Postgres instance)
and its own `nginx/conf.d/projectname.conf` (one server block).

## 3. Install this project's on-demand backend

```bash
sudo cp infra/systemd/asto-backend.socket   /etc/systemd/system/
sudo cp infra/systemd/asto-backend.service  /etc/systemd/system/
sudo cp infra/systemd/asto-backend-idle.timer   /etc/systemd/system/
sudo cp infra/systemd/asto-backend-idle.service /etc/systemd/system/

chmod +x infra/scripts/idle_stop_watcher.sh
chmod +x infra/scripts/run_ingestion.sh

sudo systemctl daemon-reload
sudo systemctl enable --now asto-backend.socket
sudo systemctl enable --now asto-backend-idle.timer
```

The backend process does **not** start yet — it starts on the first
real request to port 8011, and stops again after 10 idle minutes.
Verify:

```bash
sudo systemctl status asto-backend.socket    # active (listening)
sudo systemctl status asto-backend.service    # inactive (dead) until first request
curl http://127.0.0.1:8011/health
sudo systemctl status asto-backend.service    # now active (running)
```

## 4. Set a billing alarm (do this before onboarding real traffic)

AWS Console → CloudWatch → Alarms → Create Alarm → Billing →
`Total Estimated Charge > $0`. This is the cheapest insurance you'll
ever set up on a multi-project free-tier box.

## 5. Repeat steps 3 for each additional project

Each new project gets:
- Its own `<project>.socket` / `<project>.service` pair, on its own port
- Its own idle-timeout timer
- Its own `nginx/conf.d/<project>.conf`
- Its own database inside the **one** shared Postgres instance
- Its own `run_ingestion.sh`-style batch script if it needs NLP/document processing

No project should ever run its own Postgres, Redis, or vector DB container.

---

## M6 — Backup / restore runbook

### Nightly backup (automated)

```bash
# Install the timer once
sudo cp infra/systemd/asto-backup.service infra/systemd/asto-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now asto-backup.timer
```

The `asto-backup.timer` fires at 03:00 daily and runs `run_backup.sh`,
which writes a custom-format `pg_dump` into
`backend/storage/backups/` and keeps the newest `ASTO_BACKUP_KEEP` (default 7).

**If pg_dump isn't on the host PATH** (Postgres runs in Docker):
set in the backend's environment:
```bash
ASTO_PGDUMP_COMMAND="docker compose -f /opt/projects/asto/docker-compose.yml exec -T postgres pg_dump"
```
(pg_dump's stdout is piped back to the host, so the `.dump` file still lands
in `storage/backups/` on the host.)

Manual run: `./infra/scripts/run_backup.sh`.

### Restore (on-demand, NOT scheduled)

```bash
./infra/scripts/run_restore.sh /opt/projects/asto/backend/storage/backups/asto_20260818_120000.dump
```
If `pg_restore` isn't on PATH, set `ASTO_PGRESTORE_COMMAND` to the
`docker compose ... exec -T postgres pg_restore` wrapper and make the dump
reachable inside that context. **Restore overwrites the target DB** — always
restore to a scratch/empty database first, then verify, before touching prod.

## M3 — Maintenance runbook (VACUUM/REINDEX)

```bash
sudo cp infra/systemd/asto-maintenance.service infra/systemd/asto-maintenance.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now asto-maintenance.timer
```

The `asto-maintenance.timer` fires Sunday 04:00 and runs `run_maintenance.sh`,
which `VACUUM (ANALYZE)`s `documents`/`document_chunks` and `REINDEX INDEX
CONCURRENTLY`s the pgvector HNSW + FTS GIN indexes when dead-tuple bloat
exceeds 0.2 (override with `--reindex-threshold`).

Manual: `./infra/scripts/run_maintenance.sh --dry-run` (report only), or run
it for real. Safe to run any time — CONCURRENTLY keeps the table available.

## M5 — Retention runbook (GDPR/privacy)

```bash
sudo cp infra/systemd/asto-retention.service infra/systemd/asto-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now asto-retention.timer
```

The `asto-retention.timer` fires at 02:30 daily and runs `run_retention.sh`,
which deletes rows older than the per-table policy in `scripts/retention.py`
(audit_log 730d, login_attempts 90d, knowledge_gaps 365d, feedback 730d,
notifications 365d). Each run is itself audit-logged before any deletion.

Manual: `./infra/scripts/run_retention.sh --dry-run` to preview counts, then
run it for real.
