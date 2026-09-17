#!/bin/bash
set -Eeuo pipefail

BACKUP_SCRIPT="$HOME/clearskin_spa_app/peach_suite_backup.sh"
LOG_DIR="$HOME/PostgresBackups/Logs"
SUCCESS_FILE="$LOG_DIR/last_core_backup_success"
LOCK_DIR="$LOG_DIR/backup_scheduler.lock"
SCHEDULE_HOUR=22
FORCE_BACKUP=0

if [[ "${1:-}" == "--force" ]]; then
    FORCE_BACKUP=1
    shift
fi

if [[ "$#" -gt 0 ]]; then
    echo "Usage: $0 [--force]"
    exit 2
fi

mkdir -p "$LOG_DIR"

LOCK_PID_FILE="$LOCK_DIR/pid"

acquire_backup_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        printf "%s\n" "$$" > "$LOCK_PID_FILE"
        return 0
    fi

    local existing_pid=""

    if [[ -f "$LOCK_PID_FILE" ]]; then
        existing_pid="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    fi

    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
        echo "Backup scheduler: another backup check or backup is already running."
        echo "Active backup PID: $existing_pid"
        return 1
    fi

    echo "Backup scheduler: removing stale backup lock."
    rm -rf "$LOCK_DIR"

    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "ERROR: Backup scheduler could not acquire its lock."
        exit 1
    fi

    printf "%s\n" "$$" > "$LOCK_PID_FILE"
    return 0
}

if ! acquire_backup_lock; then
    exit 0
fi

trap 'rm -rf "$LOCK_DIR" 2>/dev/null || true' EXIT

if [[ ! -x "$BACKUP_SCRIPT" ]]; then
    echo "ERROR: Canonical backup script is missing or not executable:"
    echo "$BACKUP_SCRIPT"
    exit 1
fi

LATEST_BOUNDARY_EPOCH=$(
    /usr/bin/python3 - <<PY
from datetime import datetime, timedelta

now = datetime.now().astimezone()
boundary = now.replace(
    hour=$SCHEDULE_HOUR,
    minute=0,
    second=0,
    microsecond=0,
)

if now < boundary:
    boundary -= timedelta(days=1)

print(int(boundary.timestamp()))
PY
)

LAST_SUCCESS_EPOCH=0

if [[ -f "$SUCCESS_FILE" ]]; then
    LAST_SUCCESS_EPOCH=$(/usr/bin/stat -f '%m' "$SUCCESS_FILE")
fi

echo "========================================================="
echo "Peach Suite Pro Backup Scheduler"
echo "Checked: $(/bin/date)"
echo "Latest required 10:00 PM boundary: $(/bin/date -r "$LATEST_BOUNDARY_EPOCH")"

if [[ "$LAST_SUCCESS_EPOCH" -gt 0 ]]; then
    echo "Last successful core backup: $(/bin/date -r "$LAST_SUCCESS_EPOCH")"
else
    echo "Last successful core backup: none recorded"
fi

if [[ "$FORCE_BACKUP" -eq 1 ]]; then
    echo "Backup mode: FORCE"
    echo "Starting canonical Peach Suite Pro backup..."
    echo "========================================================="

    "$BACKUP_SCRIPT"
    exit 0
fi

if [[ "$LAST_SUCCESS_EPOCH" -ge "$LATEST_BOUNDARY_EPOCH" ]]; then
    echo "Backup status: CURRENT"
    echo "No backup is required."
    echo "========================================================="
    exit 0
fi

echo "Backup status: DUE"
echo "Starting canonical Peach Suite Pro backup..."
echo "========================================================="

"$BACKUP_SCRIPT"
