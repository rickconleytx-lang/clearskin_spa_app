"""Read one complete, workspace-scoped PeachPOS event for editing.

Caller must authorize the user and own a consistent read-only transaction.
Never reuse display-formatted Event Details data as editable input.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class EventEditReadError(ValueError):
    """Saved event cannot safely be represented for editing."""


_EVENT_COLS = (
    "event_id", "event_revision", "event_name", "venue_name",
    "street_address", "address_line2", "city", "county", "state",
    "zip_code", "parking_setup_location", "start_date", "end_date",
    "timezone_name", "contact_name", "contact_phone", "contact_email",
    "permits_obtained", "event_status", "is_public", "public_description",
    "notes_1", "notes_2",
)

_DAY_COLS = (
    "daily_schedule_id", "operating_date", "opens_at", "closes_at",
    "setup_at", "breakdown_at", "daily_notes",
)

_UNIT_COLS = (
    "daily_schedule_id", "unit_assignment_id", "event_unit_id", "is_active",
)

_SHIFT_COLS = (
    "daily_schedule_id", "employee_id", "unit_assignment_id",
    "shift_start_at", "shift_end_at", "shift_role", "shift_notes", "is_active",
)

_CUSTOM_COLS = ("slot_number", "field_label_snapshot", "field_value")


def _select(cur, table, columns, scope, *, order="", one=False):
    # All table names and column names are developer-owned constants.
    statement = (
        "SELECT " + ", ".join(columns) + " FROM public." + table
        + " WHERE spa_id = %s AND business_unit_id = %s AND event_id = %s"
        + (" ORDER BY " + order if order else "")
    )
    cur.execute(statement, scope)

    if one:
        row = cur.fetchone()
        return dict(zip(columns, row)) if row is not None else None

    return [
        dict(zip(columns, row))
        for row in cur.fetchall()
    ]


def _local_datetime(value, zone):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EventEditReadError("A saved event timestamp is invalid.")
    return value.astimezone(zone)


def _clock(value, zone):
    if value is None:
        return None
    return _local_datetime(value, zone).strftime("%H:%M")


def _text(value):
    return "" if value is None else str(value)


def load_event_edit_payload(conn, *, event_id, spa_id, workspace_id):
    """Return a form-compatible event draft, or None outside this scope.

    No writes, no lock acquisition and no commits. The endpoint must
    check administrator permissions and use a REPEATABLE READ
    READ ONLY transaction.
    """
    for name, value in (
        ("event_id", event_id),
        ("spa_id", spa_id),
        ("workspace_id", workspace_id),
    ):
        if type(value) is not int or value <= 0:
            raise EventEditReadError("Invalid " + name + ".")

    scope = (spa_id, workspace_id, event_id)
    cur = conn.cursor()

    try:
        saved = _select(
            cur,
            "event_calendar_events",
            _EVENT_COLS,
            scope,
            one=True,
        )

        if saved is None:
            return None

        start = saved["start_date"]
        end = saved["end_date"]

        if type(start) is not date or type(end) is not date:
            raise EventEditReadError("Saved event dates are invalid.")

        span = (end - start).days + 1

        if not 1 <= span <= 366:
            raise EventEditReadError(
                "Saved event date range exceeds 366 days."
            )

        try:
            zone = ZoneInfo(saved["timezone_name"] or "")
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise EventEditReadError(
                "Saved event time zone is unavailable."
            ) from None

        days = {}

        for offset in range(span):
            key = (start + timedelta(days=offset)).isoformat()

            days[key] = {
                "date": key,
                "operating": False,
                "opens": None,
                "closes": None,
                "closes_next_day": False,
                "setup": None,
                "breakdown": None,
                "notes": "",
                "equipment_ids": [],
                "shifts": [],
            }

        schedule_ids = {}

        for record in _select(
            cur,
            "event_calendar_daily_schedules",
            _DAY_COLS,
            scope,
            order="operating_date, daily_schedule_id",
        ):
            day_date = record["operating_date"]

            if (
                type(day_date) is not date
                or day_date.isoformat() not in days
            ):
                raise EventEditReadError(
                    "Saved operating date is outside event range."
                )

            key = day_date.isoformat()

            if days[key]["operating"]:
                raise EventEditReadError(
                    "Duplicate saved operating day."
                )

            schedule_ids[record["daily_schedule_id"]] = key

            open_local = _local_datetime(record["opens_at"], zone)
            close_local = _local_datetime(record["closes_at"], zone)

            if (
                open_local.date() != day_date
                or record["closes_at"] <= record["opens_at"]
            ):
                raise EventEditReadError(
                    "Saved operating times are inconsistent."
                )

            days[key].update({
                "operating": True,
                "opens": open_local.strftime("%H:%M"),
                "closes": close_local.strftime("%H:%M"),
                "closes_next_day": (
                    close_local.date() > open_local.date()
                ),
                "setup": _clock(record["setup_at"], zone),
                "breakdown": _clock(record["breakdown_at"], zone),
                "notes": _text(record["daily_notes"]),
            })

        # Cancelled events retain inactive scheduling assignments.
        # Otherwise, exclude inactive/previously removed assignments.
        include_inactive = saved["event_status"] == "cancelled"

        assignments = {}

        for record in _select(
            cur,
            "event_calendar_unit_assignments",
            _UNIT_COLS,
            scope,
            order="daily_schedule_id, unit_assignment_id",
        ):
            if not (record["is_active"] or include_inactive):
                continue

            day_key = schedule_ids.get(record["daily_schedule_id"])

            if day_key is None:
                raise EventEditReadError(
                    "Equipment assignment has no operating day."
                )

            assignments[
                record["unit_assignment_id"]
            ] = record["event_unit_id"]

            unit_ids = days[day_key]["equipment_ids"]

            if record["event_unit_id"] not in unit_ids:
                unit_ids.append(record["event_unit_id"])

        for record in _select(
            cur,
            "event_calendar_employee_assignments",
            _SHIFT_COLS,
            scope,
            order="daily_schedule_id, shift_start_at, employee_id",
        ):
            if not (record["is_active"] or include_inactive):
                continue

            day_key = schedule_ids.get(record["daily_schedule_id"])

            if day_key is None:
                raise EventEditReadError(
                    "Employee assignment has no operating day."
                )

            unit_assignment_id = record["unit_assignment_id"]

            if (
                unit_assignment_id is not None
                and unit_assignment_id not in assignments
            ):
                raise EventEditReadError(
                    "Shift references unavailable event equipment."
                )

            shift_start = _local_datetime(
                record["shift_start_at"], zone
            )
            shift_end = _local_datetime(
                record["shift_end_at"], zone
            )

            if record["shift_end_at"] <= record["shift_start_at"]:
                raise EventEditReadError(
                    "Saved employee shift is inconsistent."
                )

            days[day_key]["shifts"].append({
                "employee_id": record["employee_id"],
                "starts": shift_start.strftime("%H:%M"),
                "ends": shift_end.strftime("%H:%M"),
                "ends_next_day": (
                    shift_end.date() > shift_start.date()
                ),
                "equipment_id": assignments.get(
                    unit_assignment_id
                ),
                "role": _text(record["shift_role"]),
                "notes": _text(record["shift_notes"]),
            })

        values = {}
        labels = {}

        for record in _select(
            cur,
            "event_calendar_custom_values",
            _CUSTOM_COLS,
            scope,
            order="slot_number",
        ):
            slot = record["slot_number"]

            if type(slot) is not int or slot not in (1, 2, 3):
                raise EventEditReadError(
                    "Saved custom-field slot is invalid."
                )

            values[str(slot)] = _text(record["field_value"])
            labels[str(slot)] = _text(
                record["field_label_snapshot"]
            )

        return {
            "event_id": saved["event_id"],
            "event_revision": saved["event_revision"],
            "timezone_name": saved["timezone_name"],
            "event": {
                "name": _text(saved["event_name"]),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "status": saved["event_status"],
                "include_on_peachweb": saved["is_public"],
                "venue_name": _text(saved["venue_name"]),
                "street_address": _text(saved["street_address"]),
                "address_line2": _text(saved["address_line2"]),
                "city": _text(saved["city"]),
                "county": _text(saved["county"]),
                "state": _text(saved["state"]),
                "zip_code": _text(saved["zip_code"]),
                "parking_setup_location": _text(
                    saved["parking_setup_location"]
                ),
                "contact_name": _text(saved["contact_name"]),
                "contact_phone": _text(saved["contact_phone"]),
                "contact_email": _text(saved["contact_email"]),
                "permits_obtained": saved["permits_obtained"],
                "public_description": _text(
                    saved["public_description"]
                ),
                "notes_1": _text(saved["notes_1"]),
                "notes_2": _text(saved["notes_2"]),
            },
            "custom_values": values,
            "custom_labels": labels,
            "days": list(days.values()),
        }

    finally:
        cur.close()
