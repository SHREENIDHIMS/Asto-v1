#!/usr/bin/env bash
#
# Systemd socket activation starts asto-backend.service on the
# first connection, but does NOT stop it again automatically. This
# script is run periodically (via asto-backend-idle.timer) to
# check for active connections and stop the service if it's been
# idle for longer than IDLE_MINUTES.
#
# This, combined with socket activation, is what lets multiple
# projects share 1 GiB RAM: only the projects actually receiving
# traffic hold memory at any given moment.
#
# Idle tracking uses a timestamp file that records when the last
# active connection was detected. This avoids the pitfall of using
# ActiveEnterTimestamp (service start time) as a proxy for last
# activity.

set -euo pipefail

SERVICE="asto-backend.service"
PORT=8011
IDLE_MINUTES=10
IDLE_SECONDS=$(( IDLE_MINUTES * 60 ))
TRACKER_DIR="/var/run/asto"
TRACKER_FILE="${TRACKER_DIR}/last_active"

if ! systemctl is-active --quiet "$SERVICE"; then
    exit 0   # already stopped, nothing to do
fi

# Count established connections to the backend port right now.
ACTIVE_CONNECTIONS=$(ss -tn state established "( dport = :$PORT or sport = :$PORT )" | tail -n +2 | wc -l)

if [ "$ACTIVE_CONNECTIONS" -gt 0 ]; then
    # Traffic is flowing — update the last-active timestamp.
    mkdir -p "$TRACKER_DIR"
    date +%s > "$TRACKER_FILE"
    exit 0
fi

# No active connections right now. Check the last-active timestamp.
if [ ! -f "$TRACKER_FILE" ]; then
    # No tracker file yet — service just started, give it time.
    exit 0
fi

LAST_ACTIVE=$(cat "$TRACKER_FILE")
NOW_EPOCH=$(date +%s)
IDLE_THRESHOLD_SECONDS=$(( IDLE_MINUTES * 60 ))
IDLE_SECONDS=$(( NOW_EPOCH - LAST_ACTIVE ))

if [ "$IDLE_SECONDS" -ge "$IDLE_THRESHOLD_SECONDS" ]; then
    logger -t idle_stop_watcher "Stopping $SERVICE after ${IDLE_MINUTES}m idle (last active ${IDLE_SECONDS}s ago)"
    systemctl stop "$SERVICE"
    rm -f "$TRACKER_FILE"
fi
