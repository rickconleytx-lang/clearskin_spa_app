"""Bounded, read-only annual summaries for one PeachPOS workspace.

The Month calendar's detailed reader intentionally limits windows to 45 days.
Year View uses a single, parameterized 12-month aggregate query instead.
Caller owns the connection and a READ ONLY transaction; no commits/writes.
"""
from datetime import date


class EventYearReadError(ValueError):
    """The requested annual calendar summary is not valid."""


YEAR_SQL = """
SELECT
    d.operating_date,
    COUNT(DISTINCT d.event_id) FILTER (
        WHERE e.event_status <> 'cancelled'
    ) AS active_event_count,
    COUNT(DISTINCT a.event_unit_id) FILTER (
        WHERE e.event_status <> 'cancelled'
    ) AS active_unit_count,
    COUNT(DISTINCT d.event_id) FILTER (
        WHERE e.event_status = 'cancelled'
    ) AS cancelled_event_count
FROM public.event_calendar_daily_schedules AS d
JOIN public.event_calendar_events AS e
  ON e.spa_id = d.spa_id
 AND e.business_unit_id = d.business_unit_id
 AND e.event_id = d.event_id
LEFT JOIN public.event_calendar_unit_assignments AS a
  ON a.spa_id = d.spa_id
 AND a.business_unit_id = d.business_unit_id
 AND a.event_id = d.event_id
 AND a.daily_schedule_id = d.daily_schedule_id
 AND a.is_active = TRUE
WHERE d.spa_id = %s
  AND d.business_unit_id = %s
  AND d.operating_date >= %s
  AND d.operating_date < %s
  AND NOT EXISTS (
       SELECT 1 FROM public.event_calendar_view_metadata AS archive
       WHERE archive.event_id = e.event_id AND archive.spa_id = e.spa_id
         AND archive.business_unit_id = e.business_unit_id
         AND archive.archived_at IS NOT NULL
   )
GROUP BY d.operating_date
ORDER BY d.operating_date
"""


def list_year_day_summaries(conn, spa_id, workspace_id, year):
    """Return one summary per operating date; exclude private event data.

    COUNT DISTINCT keeps a three-truck event as one event and three units.
    Cancelled events remain separately countable but never count as active.
    """
    if any(type(value) is not int or value <= 0
           for value in (spa_id, workspace_id)):
        raise EventYearReadError("Valid business and workspace required.")
    if type(year) is not int or not 2000 <= year <= 2100:
        raise EventYearReadError("Invalid calendar year.")

    first = date(year, 1, 1)
    following = date(year + 1, 1, 1)
    cursor = conn.cursor()
    try:
        cursor.execute(
            YEAR_SQL, (spa_id, workspace_id, first, following)
        )
        records = cursor.fetchall()
    finally:
        cursor.close()

    summaries = []
    seen = set()
    for record in records:
        if len(record) != 4:
            raise EventYearReadError("Invalid annual calendar result.")
        day, events, units, cancelled = record
        if type(day) is not date or not first <= day < following:
            raise EventYearReadError("Invalid annual operating date.")
        if day in seen:
            raise EventYearReadError("Repeated annual operating date.")
        seen.add(day)
        if any(type(n) is not int or n < 0
               for n in (events, units, cancelled)):
            raise EventYearReadError("Invalid annual event counts.")
        summaries.append({
            "date": day,
            "events": events,
            "units": units,
            "cancelled": cancelled,
        })
    return summaries
