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
PG_RESTORE="/Library/PostgreSQL/18/bin/pg_restore"
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
DEVELOPER="$HOME/Developer"
FLASK_INVENTORY="$HOME/flask_inventory"
JUST_PEACHY_DATA="$HOME/Desktop/Just Peachy Data"
SCREEN_SHOTS="$HOME/Desktop/Screen Shots"
SCRIPTS="$HOME/Scripts"

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

if [[ ! -x "$PG_RESTORE" ]]; then
    echo "ERROR: pg_restore was not found at:"
    echo "$PG_RESTORE"
    exit 1
fi

PEACHVAULT_AVAILABLE=0
PEACHVAULT_SYNC_FAILED=0

if [[ -d "$SSD_MOUNT" ]]; then
    PEACHVAULT_AVAILABLE=1
    mkdir -p "$SSD_ROOT"
else
    echo "WARNING: PeachVault is not mounted."
    echo "The core backup will continue to iCloud."
    echo "PeachVault sync will remain pending."
    echo
fi

if [[ ! -d "$ICLOUD_BASE" ]]; then
    echo "ERROR: The iCloud Drive folder was not found:"
    echo "$ICLOUD_BASE"
    exit 1
fi

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
    rm -f "$LOCAL_DB_FILE"
    echo "ERROR: PostgreSQL backup was not created or is empty."
    exit 1
fi

echo "Verifying local PostgreSQL backup archive..."

if ! "$PG_RESTORE" -l "$LOCAL_DB_FILE" >/dev/null 2>&1; then
    rm -f "$LOCAL_DB_FILE"
    echo "ERROR: pg_restore could not verify the local backup archive."
    exit 1
fi

echo "Local PostgreSQL backup VERIFIED."
echo

# ---------------------------------------------------------
# CREATE VERIFIED RENDER POSTGRESQL BACKUP
# ---------------------------------------------------------

echo "Creating verified Render PostgreSQL backup..."

"$HOME/Scripts/backup_clearskin_render.sh"

echo "Render PostgreSQL backup VERIFIED."
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

    echo "  → iCloud Drive"
    mkdir -p "$ICLOUD_ROOT/$destination_name"

    rsync -av \
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

    if [[ "$PEACHVAULT_AVAILABLE" -eq 1 && "$PEACHVAULT_SYNC_FAILED" -eq 0 ]]; then
        echo "  → PeachVault"

        if ! mkdir -p "$SSD_ROOT/$destination_name"; then
            echo "WARNING: PeachVault became unavailable."
            echo "PeachVault sync will remain pending."
            PEACHVAULT_SYNC_FAILED=1
        elif ! rsync -av \
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
            "$SSD_ROOT/$destination_name/"; then
            echo "WARNING: PeachVault sync failed or the drive disconnected."
            echo "The core iCloud backup will continue."
            PEACHVAULT_SYNC_FAILED=1
        fi
    else
        echo "  → PeachVault skipped (sync pending)"
    fi
        
        echo
    }

# ---------------------------------------------------------
# CREATE VERIFIED GIT BUNDLES
# ---------------------------------------------------------

GIT_BUNDLE_DIR="$HOME/PostgresBackups/GitBundles"

mkdir -p "$GIT_BUNDLE_DIR"

create_git_bundle() {
    local repo="$1"
    local bundle_name="$2"
    local bundle_file="$GIT_BUNDLE_DIR/$bundle_name.bundle"
    local temp_bundle="$bundle_file.tmp"

    if [[ ! -d "$repo/.git" ]]; then
        echo "ERROR: Git repository was not found:"
        echo "$repo"
        exit 1
    fi

    echo "Creating Git bundle:"
    echo "$repo"

    rm -f "$temp_bundle"

    git -C "$repo" bundle create "$temp_bundle" --all

    if ! git -C "$repo" bundle verify "$temp_bundle" >/dev/null 2>&1; then
        rm -f "$temp_bundle"
        echo "ERROR: Git bundle verification failed for:"
        echo "$repo"
        exit 1
    fi

    mv "$temp_bundle" "$bundle_file"

    echo "Git bundle VERIFIED:"
    echo "$bundle_file"
    echo
}

create_git_bundle     "$PEACH_SUITE_APP"     "clearskin_spa_app"

create_git_bundle     "$HOME/Developer/PeachSuiteProMasterAdmin"     "PeachSuiteProMasterAdmin"

create_git_bundle     "$HOME/Developer/PeachCCU"     "PeachCCU"

create_git_bundle     "$FLASK_INVENTORY"     "flask_inventory"

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

copy_folder \
    "$DEVELOPER" \
    "Developer"

copy_folder \
    "$FLASK_INVENTORY" \
    "flask_inventory"

copy_folder \
    "$JUST_PEACHY_DATA" \
    "Just Peachy Data"

copy_folder \
    "$SCREEN_SHOTS" \
    "Screen Shots"

copy_folder \
    "$SCRIPTS" \
    "Scripts"

if [[ "$MISSING_COUNT" -gt 0 ]]; then
    echo
    echo "ERROR: $MISSING_COUNT required source folder(s) were missing."
    echo "Backup completion record will not be written."
    exit 1
fi

# ---------------------------------------------------------
# CREATE COMPLETION RECORD
# ---------------------------------------------------------

if [[ "$PEACHVAULT_AVAILABLE" -eq 1 && "$PEACHVAULT_SYNC_FAILED" -eq 0 ]]; then
    PEACHVAULT_STATUS="Synced: $SSD_ROOT"
elif [[ "$PEACHVAULT_AVAILABLE" -eq 1 ]]; then
    PEACHVAULT_STATUS="Sync pending: PeachVault disconnected or sync failed"
else
    PEACHVAULT_STATUS="Sync pending: PeachVault is not mounted"
fi

COMPLETION_TEXT="Peach Suite Pro backup completed: $(date)
Local database backup: $LOCAL_DB_FILE
Git bundles: $GIT_BUNDLE_DIR
PeachVault: $PEACHVAULT_STATUS
iCloud destination: $ICLOUD_ROOT"

printf "%s\n" "$COMPLETION_TEXT" \
    > "$ICLOUD_ROOT/Last Backup.txt"

mkdir -p "$ICLOUD_ROOT/Backup Logs"

cp -p "$LOG_FILE" \
    "$ICLOUD_ROOT/Backup Logs/"

if [[ "$PEACHVAULT_AVAILABLE" -eq 1 && "$PEACHVAULT_SYNC_FAILED" -eq 0 ]]; then
    if printf "%s\n" "$COMPLETION_TEXT" > "$SSD_ROOT/Last Backup.txt" \
        && mkdir -p "$SSD_ROOT/Backup Logs" \
        && cp -p "$LOG_FILE" "$SSD_ROOT/Backup Logs/"; then
        rm -f "$LOG_DIR/peachvault_sync_pending"
    else
        PEACHVAULT_SYNC_FAILED=1
        PEACHVAULT_STATUS="Sync pending: PeachVault disconnected or sync failed"

        COMPLETION_TEXT="Peach Suite Pro backup completed: $(date)
Local database backup: $LOCAL_DB_FILE
Git bundles: $GIT_BUNDLE_DIR
PeachVault: $PEACHVAULT_STATUS
iCloud destination: $ICLOUD_ROOT"

        printf "%s\n" "$COMPLETION_TEXT" \
            > "$ICLOUD_ROOT/Last Backup.txt"

        printf "%s\n" "$(date)" \
            > "$LOG_DIR/peachvault_sync_pending"

        echo "WARNING: PeachVault disconnected while writing completion records."
    fi
else
    printf "%s\n" "$(date)" \
        > "$LOG_DIR/peachvault_sync_pending"
fi

CORE_SUCCESS_FILE="$LOG_DIR/last_core_backup_success"

printf "%s\n" "$(date)" > "$CORE_SUCCESS_FILE"

echo "========================================================="
echo "Backup completed: $(date)"
echo "PeachVault: $PEACHVAULT_STATUS"
echo "iCloud: $ICLOUD_ROOT"
echo "Core success marker: $CORE_SUCCESS_FILE"
echo "Log: $LOG_FILE"
echo "========================================================="

echo
echo "All Peach Suite Pro backup sources completed successfully."
