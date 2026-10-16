"""Backup status metadata validation; no credentials or raw logs."""

from datetime import datetime, timedelta, timezone
from uuid import UUID


class BackupReportValidationError(ValueError):
    pass


FAILURE_CODES = {
    "local_archive_failed",
    "render_archive_failed",
    "git_bundle_failed",
    "source_missing",
    "icloud_failed",
    "peachvault_failed",
    "both_destinations_failed",
    "completion_record_failed",
    "backup_failed",
}

REPORT_FIELDS = {
    "report_uuid", "reported_at", "run_started_at", "run_finished_at",
    "last_success_at", "run_status", "icloud_status",
    "peachvault_status", "failure_code",
}


def _timestamp(value, field, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise BackupReportValidationError(f"Invalid {field}.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BackupReportValidationError(f"Invalid {field}.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackupReportValidationError(f"{field} requires a timezone.")
    return parsed.astimezone(timezone.utc)


def validate_backup_report(data, *, now=None):
    """Return typed metadata. Authentication and source identity are external."""
    if not isinstance(data, dict) or set(data) - REPORT_FIELDS:
        raise BackupReportValidationError("Invalid report fields.")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Server time requires a timezone.")
    now = now.astimezone(timezone.utc)

    raw_uuid = data.get("report_uuid")
    if not isinstance(raw_uuid, str) or len(raw_uuid) != 36:
        raise BackupReportValidationError("Invalid report_uuid.")
    try:
        report_uuid = UUID(raw_uuid)
    except ValueError:
        raise BackupReportValidationError("Invalid report_uuid.") from None
    if str(report_uuid) != raw_uuid or report_uuid.int == 0:
        raise BackupReportValidationError("Invalid report_uuid.")

    result = {"report_uuid": str(report_uuid)}
    for field in ("reported_at", "run_started_at", "run_finished_at",
                  "last_success_at"):
        result[field] = _timestamp(
            data.get(field), field, required=(field == "reported_at")
        )
        if result[field] and result[field] > now + timedelta(minutes=5):
            raise BackupReportValidationError(f"{field} is in the future.")

    reported = result["reported_at"]
    if reported < now - timedelta(minutes=15):
        raise BackupReportValidationError("Report timestamp is stale.")

    for field, allowed in (
        ("run_status", {"running", "success", "failed", "idle"}),
        ("icloud_status", {"unknown", "success", "failed"}),
        ("peachvault_status", {"unknown", "success", "failed"}),
    ):
        value = data.get(field)
        if not isinstance(value, str) or value not in allowed:
            raise BackupReportValidationError(f"Invalid {field}.")
        result[field] = value

    failure = data.get("failure_code")
    if failure is not None and (
        not isinstance(failure, str) or failure not in FAILURE_CODES
    ):
        raise BackupReportValidationError("Invalid failure_code.")
    result["failure_code"] = failure

    start = result["run_started_at"]
    finish = result["run_finished_at"]
    success = result["last_success_at"]
    if finish and (not start or finish < start):
        raise BackupReportValidationError("Invalid run chronology.")
    for field in ("run_started_at", "run_finished_at", "last_success_at"):
        if result[field] and result[field] > reported:
            raise BackupReportValidationError(f"{field} exceeds reported_at.")

    status = result["run_status"]
    if status == "running" and (not start or finish or failure):
        raise BackupReportValidationError("Invalid running report.")
    if status == "success":
        if (
            not start or not finish or success != finish or failure
            or result["icloud_status"] != "success"
            or result["peachvault_status"] != "success"
        ):
            raise BackupReportValidationError("Invalid success report.")
    if status == "failed" and (not start or not finish or not failure):
        raise BackupReportValidationError("Invalid failure report.")
    if failure and status != "failed":
        raise BackupReportValidationError("Failure code requires failed status.")

    return result


def backup_schedule_state(
    *,
    now,
    last_success_at,
    timezone_name="America/Chicago",
    schedule_hour=22,
    grace_minutes=60,
):
    """Evaluate the latest required daily backup in its configured timezone."""
    from datetime import time
    from zoneinfo import ZoneInfo

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Server time requires a timezone.")
    if type(schedule_hour) is not int or not 0 <= schedule_hour <= 23:
        raise ValueError("Invalid schedule hour.")
    if type(grace_minutes) is not int or not 5 <= grace_minutes <= 1440:
        raise ValueError("Invalid grace period.")
    if last_success_at is not None and (
        last_success_at.tzinfo is None
        or last_success_at.utcoffset() is None
    ):
        raise ValueError("Success time requires a timezone.")

    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    boundary_date = local_now.date()
    boundary = datetime.combine(
        boundary_date, time(hour=schedule_hour), tzinfo=zone
    )
    if local_now < boundary:
        boundary_date -= timedelta(days=1)
        boundary = datetime.combine(
            boundary_date, time(hour=schedule_hour), tzinfo=zone
        )

    boundary_utc = boundary.astimezone(timezone.utc)
    deadline = boundary_utc + timedelta(minutes=grace_minutes)
    now_utc = now.astimezone(timezone.utc)
    success_utc = (
        last_success_at.astimezone(timezone.utc)
        if last_success_at is not None else None
    )
    if success_utc is not None and success_utc > now_utc:
        raise ValueError("Success time cannot exceed server time.")

    current = success_utc is not None and success_utc >= boundary_utc
    return {
        "latest_required_boundary": boundary_utc,
        "deadline": deadline,
        "current": current,
        "overdue": not current and now_utc >= deadline,
    }


def save_backup_report(cur, *, source_key, data, now=None):
    """Store validated metadata using a standard tuple cursor.

    Caller owns commit/rollback and must process incident transitions
    in this same transaction before committing an accepted report.
    Source identity comes from server authentication, never the payload.
    """
    now = now or datetime.now(timezone.utc)
    report = validate_backup_report(data, now=now)

    cur.execute(
        """
        SELECT enabled, last_success_at
        FROM master_admin_backup_sources
        WHERE source_key = %s
        FOR UPDATE
        """,
        (source_key,),
    )
    source = cur.fetchone()
    if source is None or not source[0]:
        raise BackupReportValidationError("Backup source is not enabled.")

    cur.execute(
        """
        SELECT backup_report_id
        FROM master_admin_backup_reports
        WHERE source_key = %s AND report_uuid = %s
        """,
        (source_key, report["report_uuid"]),
    )
    existing = cur.fetchone()
    if existing:
        return {"status": "duplicate", "report_id": existing[0]}

    cur.execute(
        """
        SELECT MAX(reported_at)
        FROM master_admin_backup_reports
        WHERE source_key = %s
        """,
        (source_key,),
    )
    latest_reported_at = cur.fetchone()[0]
    if latest_reported_at and report["reported_at"] <= latest_reported_at:
        return {"status": "out_of_order", "report_id": None}

    previous_success = source[1]
    if (
        report["run_status"] in {"success", "failed"}
        and previous_success is not None
        and report["run_finished_at"] < previous_success
    ):
        raise BackupReportValidationError("Backup result predates known success.")

    cur.execute(
        """
        INSERT INTO master_admin_backup_reports (
            source_key, report_uuid, reported_at, received_at,
            run_started_at, run_finished_at, last_success_at,
            run_status, icloud_status, peachvault_status, failure_code
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING backup_report_id
        """,
        (
            source_key, report["report_uuid"], report["reported_at"], now,
            report["run_started_at"], report["run_finished_at"],
            report["last_success_at"], report["run_status"],
            report["icloud_status"], report["peachvault_status"],
            report["failure_code"],
        ),
    )
    report_id = cur.fetchone()[0]

    # Only an explicit successful run can advance verified success.
    success_at = (
        report["run_finished_at"]
        if report["run_status"] == "success" else None
    )
    cur.execute(
        """
        UPDATE master_admin_backup_sources
        SET last_received_at = %s,
            last_success_at = CASE
                WHEN %s::timestamptz IS NULL THEN last_success_at
                WHEN last_success_at IS NULL THEN %s::timestamptz
                ELSE GREATEST(last_success_at, %s::timestamptz)
            END
        WHERE source_key = %s
        """,
        (now, success_at, success_at, success_at, source_key),
    )
    return {
        "status": "accepted",
        "report_id": report_id,
        "report": report,
    }
