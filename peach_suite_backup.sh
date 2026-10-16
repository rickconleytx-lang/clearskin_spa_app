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
ICLOUD_AVAILABLE=0
ICLOUD_SYNC_FAILED=0

if [[ -d "$SSD_MOUNT" ]]; then
    if mkdir -p "$SSD_ROOT"; then
        PEACHVAULT_AVAILABLE=1
    else
        PEACHVAULT_SYNC_FAILED=1
        echo "ERROR: Cannot prepare PeachVault destination."
    fi
else
    PEACHVAULT_SYNC_FAILED=1
    echo "ERROR: PeachVault is not mounted."
fi

if [[ -d "$ICLOUD_BASE" ]]; then
    if mkdir -p "$ICLOUD_ROOT"; then
        ICLOUD_AVAILABLE=1
    else
        ICLOUD_SYNC_FAILED=1
        echo "ERROR: Cannot prepare iCloud destination."
    fi
else
    ICLOUD_SYNC_FAILED=1
    echo "ERROR: iCloud Drive folder was not found."
fi

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

copy_to_destination() {
    local source="$1"
    local destination="$2"

    if ! mkdir -p "$destination"; then
        echo "ERROR: Cannot prepare destination: $destination"
        return 1
    fi

    if rsync -av \
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
        "$source/" "$destination/"; then
        return 0
    else
        local copy_status=$?
        echo "ERROR: rsync failed (exit $copy_status): $destination"
        return "$copy_status"
    fi
}

copy_folder() {
    local source="$1"
    local destination_name="$2"

    if [[ ! -d "$source" ]]; then
        echo "ERROR: Required source folder was not found: $source"
        MISSING_COUNT=$((MISSING_COUNT + 1))
        return 0
    fi

    echo "Backing up: $source"

    if [[ "$PEACHVAULT_AVAILABLE" -eq 1 ]]; then
        echo "  → PeachVault"
        if ! copy_to_destination "$source" "$SSD_ROOT/$destination_name"; then
            PEACHVAULT_SYNC_FAILED=1
        fi
    else
        echo "  → PeachVault unavailable"
    fi

    if [[ "$ICLOUD_AVAILABLE" -eq 1 ]]; then
        echo "  → iCloud Drive"
        if ! copy_to_destination "$source" "$ICLOUD_ROOT/$destination_name"; then
            ICLOUD_SYNC_FAILED=1
        fi
    else
        echo "  → iCloud Drive unavailable"
    fi

    echo
    return 0
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

# ---------------------------------------------------------
# RECORD EACH DESTINATION AND OVERALL RESULT
# ---------------------------------------------------------

CORE_SUCCESS_FILE="$LOG_DIR/last_core_backup_success"

write_destination_record() {
    local root="$1"
    if printf "%s\n" "$COMPLETION_TEXT" > "$root/Last Backup.txt" \
        && mkdir -p "$root/Backup Logs" \
        && cp -p "$LOG_FILE" "$root/Backup Logs/"; then
        return 0
    else
        echo "ERROR: Could not write completion records: $root"
        return 1
    fi
}

COMPLETION_TEXT="Peach Suite Pro destination copy completed: $(date)
Local database archive: $LOCAL_DB_FILE
Git bundles: $GIT_BUNDLE_DIR
Archive checks: pg_restore listing and git bundle verification
Required missing sources: $MISSING_COUNT
Run log: $LOG_FILE"

if [[ "$MISSING_COUNT" -eq 0 && "$PEACHVAULT_SYNC_FAILED" -eq 0 ]]; then
    if ! write_destination_record "$SSD_ROOT"; then
        PEACHVAULT_SYNC_FAILED=1
    fi
fi

if [[ "$MISSING_COUNT" -eq 0 && "$ICLOUD_SYNC_FAILED" -eq 0 ]]; then
    if ! write_destination_record "$ICLOUD_ROOT"; then
        ICLOUD_SYNC_FAILED=1
    fi
fi

record_destination_status() {
    local name="$1"
    local failed="$2"
    if [[ "$failed" -eq 0 && "$MISSING_COUNT" -eq 0 ]]; then
        printf "%s\n" "$(date)" > "$LOG_DIR/last_${name}_backup_success"
        rm -f "$LOG_DIR/${name}_sync_pending"
        echo "$name: SUCCESS"
    else
        printf "%s\n" "Backup incomplete: $(date); see $LOG_FILE" \
            > "$LOG_DIR/${name}_sync_pending"
        echo "$name: FAILED / INCOMPLETE"
    fi
}

record_destination_status "peachvault" "$PEACHVAULT_SYNC_FAILED"
record_destination_status "icloud" "$ICLOUD_SYNC_FAILED"

if [[ "$MISSING_COUNT" -gt 0 || "$PEACHVAULT_SYNC_FAILED" -ne 0 || "$ICLOUD_SYNC_FAILED" -ne 0 ]]; then
    echo "ERROR: Backup incomplete. Missing required sources: $MISSING_COUNT"
    echo "Overall success marker was not updated."
    echo "Log: $LOG_FILE"
    exit 1
fi

printf "%s\n" "$(date)" > "$CORE_SUCCESS_FILE"

echo "========================================================="
echo "Backup completed successfully to BOTH destinations: $(date)"
echo "Core success marker: $CORE_SUCCESS_FILE"
echo "Log: $LOG_FILE"
echo "========================================================="
