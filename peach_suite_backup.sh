#!/bin/bash

set -Eeuo pipefail

# =========================================================
# PEACH SUITE PRO BACKUP
# Local PostgreSQL + Project Files + Documents
# Destinations: PeachVault SSD and iCloud Drive
# =========================================================

STAMP=$(date +%Y_%m_%d_%H%M%S)

# ---------------------------------------------------------
# POSTGRESQL SETTINGS
# ---------------------------------------------------------

PG_DUMP="/Library/PostgreSQL/18/bin/pg_dump"
DB_USER="postgres"
DB_NAME="clearskin_spa"

LOCAL_DB_DIR="$HOME/PostgresBackups/LocalDB"
LOCAL_DB_FILE="$LOCAL_DB_DIR/clearskin_local_$STAMP.backup"

# ---------------------------------------------------------
# BACKUP SOURCES
# ---------------------------------------------------------

RENDER_DATABASE_EXPORTS="$HOME/ClearSkin Database Backups"
PEACH_SUITE_APP="$HOME/clearskin_spa_app"
PGADMIN_BACKUPS="$HOME/pgAdmin Backups"
POSTGRES_BACKUPS="$HOME/PostgresBackups"
PEACH_SUITE_DOCUMENTS="$HOME/Documents/Peach Suite Pro"
PEACH_SUITE_HOME="$HOME/Desktop/Peach Suite Pro Home"

# ---------------------------------------------------------
# BACKUP DESTINATIONS
# ---------------------------------------------------------

SSD_MOUNT="/Volumes/PeachVault"
SSD_ROOT="$SSD_MOUNT/Peach Suite Pro Backups"

ICLOUD_BASE="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
ICLOUD_ROOT="$ICLOUD_BASE/Peach Suite Backups"

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------

LOG_DIR="$HOME/PostgresBackups/Logs"
LOG_FILE="$LOG_DIR/peach_suite_backup_$STAMP.log"

mkdir -p "$LOCAL_DB_DIR"
mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo
echo "========================================================="
echo "Peach Suite Pro Backup"
echo "Started: $(date)"
echo "========================================================="
echo

# ---------------------------------------------------------
# PREFLIGHT CHECKS
# ---------------------------------------------------------

if [[ ! -x "$PG_DUMP" ]]; then
    echo "ERROR: pg_dump was not found at:"
    echo "$PG_DUMP"
    exit 1
fi

if [[ ! -d "$SSD_MOUNT" ]]; then
    echo "ERROR: PeachVault is not mounted."
    echo "Connect the SSD and confirm this folder exists:"
    echo "$SSD_MOUNT"
    exit 1
fi

if [[ ! -d "$ICLOUD_BASE" ]]; then
    echo "ERROR: The iCloud Drive folder was not found:"
    echo "$ICLOUD_BASE"
    exit 1
fi

mkdir -p "$SSD_ROOT"
mkdir -p "$ICLOUD_ROOT"

# ---------------------------------------------------------
# CREATE FRESH LOCAL POSTGRESQL BACKUP
# ---------------------------------------------------------

echo "Creating local PostgreSQL backup..."
echo "$LOCAL_DB_FILE"

"$PG_DUMP" \
    -U "$DB_USER" \
    -Fc "$DB_NAME" \
    -f "$LOCAL_DB_FILE"

if [[ ! -s "$LOCAL_DB_FILE" ]]; then
    echo "ERROR: PostgreSQL backup was not created or is empty."
    exit 1
fi

echo "Local PostgreSQL backup completed."
echo

# ---------------------------------------------------------
# COPY FUNCTION
# ---------------------------------------------------------

MISSING_COUNT=0

copy_folder() {
    local source="$1"
    local destination_name="$2"

    if [[ ! -d "$source" ]]; then
        echo "WARNING: Source folder was not found:"
        echo "$source"
        echo

        MISSING_COUNT=$((MISSING_COUNT + 1))
        return 0
    fi

    echo "Backing up:"
    echo "$source"

    echo "  → PeachVault"
    mkdir -p "$SSD_ROOT/$destination_name"

    rsync -avE \
        --exclude='.env' \
        --exclude='.env.*' \
        --exclude='.venv/' \
        --exclude='venv/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.git/' \
        --exclude='.DS_Store' \
        --exclude='._*' \
        --exclude='.pytest_cache/' \
        --exclude='node_modules/' \
        "$source/" \
        "$SSD_ROOT/$destination_name/"

    echo "  → iCloud Drive"
    mkdir -p "$ICLOUD_ROOT/$destination_name"

    rsync -avE \
        --exclude='.env' \
        --exclude='.env.*' \
        --exclude='.venv/' \
        --exclude='venv/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.git/' \
        --exclude='.DS_Store' \
        --exclude='._*' \
        --exclude='.pytest_cache/' \
        --exclude='node_modules/' \
        "$source/" \
        "$ICLOUD_ROOT/$destination_name/"
        
        echo
    }

# ---------------------------------------------------------
# COPY ALL PEACH SUITE PRO FILES
# ---------------------------------------------------------

copy_folder \
    "$RENDER_DATABASE_EXPORTS" \
    "ClearSkin Database Backups"

copy_folder \
    "$PEACH_SUITE_APP" \
    "Peach Suite Pro App"

copy_folder \
    "$PGADMIN_BACKUPS" \
    "pgAdmin Backups"

copy_folder \
    "$POSTGRES_BACKUPS" \
    "Postgres Backups"

copy_folder \
    "$PEACH_SUITE_DOCUMENTS" \
    "Peach Suite Pro Documents"

copy_folder \
    "$PEACH_SUITE_HOME" \
    "Peach Suite Pro Home"

# ---------------------------------------------------------
# CREATE COMPLETION RECORD
# ---------------------------------------------------------

COMPLETION_TEXT="Peach Suite Pro backup completed: $(date)
Local database backup: $LOCAL_DB_FILE
SSD destination: $SSD_ROOT
iCloud destination: $ICLOUD_ROOT"

printf "%s\n" "$COMPLETION_TEXT" \
    > "$SSD_ROOT/Last Backup.txt"

printf "%s\n" "$COMPLETION_TEXT" \
    > "$ICLOUD_ROOT/Last Backup.txt"

mkdir -p "$SSD_ROOT/Backup Logs"
mkdir -p "$ICLOUD_ROOT/Backup Logs"

cp -p "$LOG_FILE" \
    "$SSD_ROOT/Backup Logs/"

cp -p "$LOG_FILE" \
    "$ICLOUD_ROOT/Backup Logs/"

echo "========================================================="
echo "Backup completed: $(date)"
echo "PeachVault: $SSD_ROOT"
echo "iCloud: $ICLOUD_ROOT"
echo "Log: $LOG_FILE"
echo "========================================================="

if [[ "$MISSING_COUNT" -gt 0 ]]; then
    echo
    echo "WARNING: $MISSING_COUNT source folder(s) were missing."
    exit 1
fi

echo
echo "All Peach Suite Pro backup sources completed successfully."
