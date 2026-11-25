"""Read-only, workspace-scoped Event Details retrieval.

Returns event information, daily operating hours, assigned
physical units and employee shifts. No database writes.
"""

from datetime import date

from services.event_calendar_month import (
    format_event_clock,
    readable_text_color,
)
from services.event_calendar_read import safe_calendar_color


EVENT_SQL = """
SELECT
    event_id, event_name, venue_name,
    street_address, address_line2,
    city, county, state, zip_code,
    start_date, end_date, timezone_name,
    event_status, notes_1, notes_2
FROM event_calendar_events
WHERE event_id = %s
  AND spa_id = %s
  AND business_unit_id = %s
"""

DAYS_SQL = """
SELECT
    daily_schedule_id, operating_date,
    opens_at, closes_at, daily_notes
FROM event_calendar_daily_schedules
WHERE event_id = %s
  AND spa_id = %s
  AND business_unit_id = %s
ORDER BY operating_date, daily_schedule_id
"""

UNITS_SQL = """
SELECT
    a.daily_schedule_id,
    a.unit_assignment_id,
    u.event_unit_id,
    u.unit_name,
    u.calendar_color
FROM event_calendar_unit_assignments a
JOIN event_units u
  ON u.event_unit_id = a.event_unit_id
 AND u.spa_id = a.spa_id
 AND u.business_unit_id = a.business_unit_id
WHERE a.event_id = %s
  AND a.spa_id = %s
  AND a.business_unit_id = %s
  AND a.is_active = TRUE
ORDER BY a.daily_schedule_id, u.unit_name
"""

EMPLOYEES_SQL = """
SELECT
    a.daily_schedule_id,
    COALESCE(
        NULLIF(
            BTRIM(CONCAT_WS(' ', p.first_name, p.last_name)),
            ''
        ),
        'Employee'
    ) AS employee_name,
    a.shift_start_at,
    a.shift_end_at,
    a.shift_role,
    a.shift_notes,
    a.unit_assignment_id
FROM event_calendar_employee_assignments a
JOIN employees p
  ON p.employee_id = a.employee_id
 AND p.spa_id = a.spa_id
WHERE a.event_id = %s
  AND a.spa_id = %s
  AND a.business_unit_id = %s
  AND a.is_active = TRUE
ORDER BY
    a.daily_schedule_id,
    a.shift_start_at,
    a.employee_assignment_id
"""


def _iso(value):
    return value.isoformat() if isinstance(value, date) else ""


def _text(value):
    return str(value).strip() if value is not None else ""


def get_event_details(conn, event_id, spa_id, workspace_id):
    """Return event details or None when not found in this scope.

    All four queries are parameterized and business/workspace scoped.
    The caller owns the database transaction and connection.
    """

    for value in (event_id, spa_id, workspace_id):
        if type(value) is not int or value <= 0:
            raise ValueError("Valid Event Calendar scope required.")

    params = (event_id, spa_id, workspace_id)
    cursor = conn.cursor()

    try:
        cursor.execute(EVENT_SQL, params)
        event_row = cursor.fetchone()

        if event_row is None:
            return None

        (
            found_id, name, venue, street, address_line2,
            city, county, state, zip_code,
            start_date, end_date, timezone_name,
            status, notes_1, notes_2,
        ) = event_row

        result = {
            "event_id": found_id,
            "name": _text(name),
            "venue": _text(venue),
            "address": {
                "street": _text(street),
                "line2": _text(address_line2),
                "city": _text(city),
                "county": _text(county),
                "state": _text(state),
                "zip_code": _text(zip_code),
            },
            "start_date": _iso(start_date),
            "end_date": _iso(end_date),
            "status": _text(status),
            "notes": [
                _text(value)
                for value in (notes_1, notes_2)
                if _text(value)
            ],
            "days": [],
        }

        cursor.execute(DAYS_SQL, params)
        raw_days = cursor.fetchall()

        by_schedule = {}

        for (
            schedule_id, operating_date,
            opens_at, closes_at, daily_notes
        ) in raw_days:
            day = {
                "date": _iso(operating_date),
                "opens": format_event_clock(
                    opens_at, timezone_name
                ),
                "closes": format_event_clock(
                    closes_at, timezone_name
                ),
                "notes": _text(daily_notes),
                "units": [],
                "employees": [],
            }

            by_schedule[schedule_id] = day
            result["days"].append(day)

        cursor.execute(UNITS_SQL, params)
        raw_units = cursor.fetchall()

        names_by_assignment = {}

        for (
            schedule_id, assignment_id,
            unit_id, unit_name, color_value
        ) in raw_units:
            if schedule_id not in by_schedule:
                continue

            color = safe_calendar_color(color_value)
            unit_name = _text(unit_name)

            unit = {
                "id": unit_id,
                "name": unit_name,
                "color": color,
                "text_color": readable_text_color(color),
            }

            by_schedule[schedule_id]["units"].append(unit)
            names_by_assignment[assignment_id] = unit_name

        cursor.execute(EMPLOYEES_SQL, params)
        raw_employees = cursor.fetchall()

        for (
            schedule_id, employee_name,
            starts_at, ends_at,
            role, notes, unit_assignment_id
        ) in raw_employees:
            if schedule_id not in by_schedule:
                continue

            by_schedule[schedule_id]["employees"].append({
                "name": _text(employee_name),
                "starts": format_event_clock(
                    starts_at, timezone_name
                ),
                "ends": format_event_clock(
                    ends_at, timezone_name
                ),
                "role": _text(role),
                "notes": _text(notes),
                "unit": names_by_assignment.get(
                    unit_assignment_id, ""
                ),
            })

        return result

    finally:
        cursor.close()
