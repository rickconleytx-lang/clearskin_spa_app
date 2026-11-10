"""Read-only, workspace-scoped PeachPOS Event Calendar queries."""

import re
from datetime import date, datetime


class EventCalendarReadError(ValueError):
    """Invalid calendar query parameters."""


COLUMNS = (
    "event_id",
    "event_name",
    "start_date",
    "end_date",
    "event_status",
    "venue_name",
    "city",
    "state",
    "timezone_name",
    "daily_schedule_id",
    "operating_date",
    "opens_at",
    "closes_at",
    "event_unit_id",
    "unit_name",
    "calendar_color",
)


CALENDAR_QUERY = """
SELECT
    e.event_id,
    e.event_name,
    e.start_date,
    e.end_date,
    e.event_status,
    e.venue_name,
    e.city,
    e.state,
    e.timezone_name,
    d.daily_schedule_id,
    d.operating_date,
    d.opens_at,
    d.closes_at,
    u.event_unit_id,
    u.unit_name,
    u.calendar_color
FROM event_calendar_events e
LEFT JOIN event_calendar_daily_schedules d
    ON d.event_id = e.event_id
   AND d.spa_id = e.spa_id
   AND d.business_unit_id = e.business_unit_id
   AND d.operating_date BETWEEN %s AND %s
LEFT JOIN event_calendar_unit_assignments a
    ON a.daily_schedule_id = d.daily_schedule_id
   AND a.event_id = e.event_id
   AND a.spa_id = e.spa_id
   AND a.business_unit_id = e.business_unit_id
   AND a.is_active = TRUE
LEFT JOIN event_units u
    ON u.event_unit_id = a.event_unit_id
   AND u.spa_id = e.spa_id
   AND u.business_unit_id = e.business_unit_id
WHERE e.spa_id = %s
  AND e.business_unit_id = %s
  AND e.start_date <= %s
  AND e.end_date >= %s
ORDER BY
    e.start_date,
    e.event_id,
    d.operating_date,
    u.unit_name
"""


def safe_calendar_color(value):
    """Use only valid six-digit CSS hex colors."""
    if (
        isinstance(value, str)
        and re.fullmatch(r"#[0-9a-fA-F]{6}", value)
    ):
        return value

    return "#64748B"


def list_event_calendar_rows(
    conn, spa_id, workspace_id, start_date, end_date
):
    """Return event/day/unit rows for an inclusive calendar window.

    Includes events without assigned trucks or operating days.
    Does not read employee details or private event contact data.
    Caller owns the connection and its transaction.
    """

    if (
        type(spa_id) is not int or spa_id <= 0
        or type(workspace_id) is not int or workspace_id <= 0
    ):
        raise EventCalendarReadError(
            "Valid business and workspace identifiers required."
        )

    if (
        not isinstance(start_date, date)
        or isinstance(start_date, datetime)
        or not isinstance(end_date, date)
        or isinstance(end_date, datetime)
    ):
        raise EventCalendarReadError(
            "Calendar dates must be date objects."
        )

    days = (end_date - start_date).days + 1

    if not 1 <= days <= 45:
        raise EventCalendarReadError(
            "Calendar query window must contain 1–45 days."
        )

    cursor = conn.cursor()

    try:
        cursor.execute(
            CALENDAR_QUERY,
            (
                start_date,
                end_date,
                spa_id,
                workspace_id,
                end_date,
                start_date,
            ),
        )
        fetched = cursor.fetchall()
    finally:
        cursor.close()

    result = []

    for row in fetched:
        if len(row) != len(COLUMNS):
            raise RuntimeError(
                "Unexpected Event Calendar query result."
            )

        item = dict(zip(COLUMNS, row))
        item["calendar_color"] = safe_calendar_color(
            item["calendar_color"]
        )
        result.append(item)

    return result
