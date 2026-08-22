#!/usr/bin/env bash
#
# Runs the appointment reminder emails as a one-shot batch job.
#
# Reminds assigned staff about appointments starting within the next 24h.
#
# Deliberately does NOT run inside the FastAPI process (rule 5) — a
# one-shot script, triggered by asto-appointment-reminders.timer.

set -euo pipefail

cd /opt/projects/asto/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting appointment reminders"
python -m scripts.appointment_reminders
echo "[$(date -Iseconds)] Appointment reminders complete"
