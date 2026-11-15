"""Restricted, read-only public PeachWeb event access.

This module does not expose administrative event records.
It does not connect to a database on its own.
"""

from datetime import date, datetime, timedelta


PUBLIC_EVENT_COLUMNS = (
    "event_id",
    "event_name",
    "venue_name",
    "city",
    "state",
    "street_address",
    "address_line2",
    "zip_code",
    "timezone_name",
    "operating_date",
    "opens_at",
    "closes_at",
)


PUBLIC_EVENT_DAY_SQL = """
SELECT
    e.event_id,
    e.event_name,
    e.venue_name,
    e.city,
    e.state,
    e.street_address,
    e.address_line2,
    e.zip_code,
    e.timezone_name,
    d.operating_date,
    d.opens_at,
    d.closes_at
FROM event_calendar_events e
JOIN event_calendar_daily_schedules d
    ON d.event_id = e.event_id
   AND d.spa_id = e.spa_id
   AND d.business_unit_id = e.business_unit_id
JOIN spas s
    ON s.spa_id = e.spa_id
   AND s.active = TRUE
JOIN business_units bu
    ON bu.spa_id = e.spa_id
   AND bu.business_unit_id = e.business_unit_id
   AND bu.is_active = TRUE
JOIN subscription_tiers st
    ON st.subscription_tier_id = s.subscription_tier_id
WHERE e.spa_id = %s
  AND e.business_unit_id = %s
  AND d.operating_date BETWEEN %s AND %s
  AND LOWER(st.tier_code) = 'pos'
  AND e.is_public IS TRUE
  AND e.event_status <> 'cancelled'
  AND NOT EXISTS (
      SELECT 1
      FROM event_calendar_view_metadata m
      WHERE m.event_id = e.event_id
        AND m.spa_id = e.spa_id
        AND m.business_unit_id = e.business_unit_id
        AND m.archived_at IS NOT NULL
  )
ORDER BY
    d.operating_date,
    e.event_name,
    e.event_id
"""


def fetch_public_event_days(
    cursor,
    *,
    spa_id,
    business_unit_id,
    window_start,
    window_end,
):
    """Read approved event days within one five-week window."""

    if (
        type(spa_id) is not int
        or spa_id <= 0
        or type(business_unit_id) is not int
        or business_unit_id <= 0
    ):
        raise ValueError("Valid business identity required.")

    if (
        type(window_start) is not date
        or type(window_end) is not date
        or window_start.weekday() != 0
        or window_end != window_start + timedelta(days=34)
    ):
        raise ValueError("Valid five-week window required.")

    cursor.execute(
        PUBLIC_EVENT_DAY_SQL,
        (
            spa_id,
            business_unit_id,
            window_start,
            window_end,
        ),
    )

    results = []

    for row in cursor.fetchall():
        if len(row) != len(PUBLIC_EVENT_COLUMNS):
            raise ValueError("Unexpected public event result.")

        results.append(dict(zip(PUBLIC_EVENT_COLUMNS, row)))

    return results
