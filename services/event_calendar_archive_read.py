"""Read-only, workspace-scoped archived event spans for calendar overlays.

Archived entries use preserved event dates, never equipment joins, because
archiving clears equipment/employee assignments. Only name/id/dates are read.
"""
from datetime import date, timedelta


def list_archived_event_spans(conn, spa_id, workspace_id, first, last):
    if any(type(v) is not int or v <= 0 for v in (spa_id, workspace_id)):
        raise ValueError("Invalid calendar workspace scope.")
    if type(first) is not date or type(last) is not date:
        raise ValueError("Invalid archived-calendar dates.")
    if not 1 <= (last - first).days + 1 <= 370:
        raise ValueError("Invalid archived-calendar window.")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT e.event_id, e.event_name, e.start_date, e.end_date
              FROM public.event_calendar_events AS e
              JOIN public.event_calendar_view_metadata AS m
                ON m.event_id = e.event_id AND m.spa_id = e.spa_id
               AND m.business_unit_id = e.business_unit_id
             WHERE e.spa_id = %s AND e.business_unit_id = %s
               AND m.archived_at IS NOT NULL
               AND e.start_date <= %s AND e.end_date >= %s
             ORDER BY e.event_id
        """, (spa_id, workspace_id, last, first))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    result = []
    for event_id, name, start, end in rows:
        if type(event_id) is not int or event_id <= 0 or type(name) is not str:
            raise ValueError("Invalid archived event result.")
        if type(start) is not date or type(end) is not date or end < start:
            raise ValueError("Invalid archived event date range.")
        result.append({"event_id": event_id, "name": name,
                       "start": max(first, start), "end": min(last, end)})
    return result


def _dates(spans):
    for span in spans:
        day = span["start"]
        while day <= span["end"]:
            yield day, span
            day += timedelta(days=1)


def overlay_archived_month(calendar, spans):
    by_day = {}
    for day, event in _dates(spans):
        by_day.setdefault(day, []).append(event)
    for week in calendar["weeks"]:
        for cell in week:
            for event in by_day.get(cell["date"], []):
                cell["entries"].append({"event_id": event["event_id"],
                                        "name": event["name"], "is_archived": True})
    return calendar


def overlay_archived_week(calendar, spans):
    by_day = {}
    for day, event in _dates(spans):
        by_day.setdefault(day, []).append(event)
    for cell in calendar["days"]:
        for event in by_day.get(cell["date"], []):
            cell["entries"].append({"event_id": event["event_id"],
                                    "name": event["name"], "is_archived": True})
    return calendar


def overlay_archived_year(calendar, spans):
    by_day = {}
    for day, event in _dates(spans):
        by_day.setdefault(day, []).append(event["name"])
    for month in calendar["months"]:
        month_names = set()
        for week in month["weeks"]:
            for cell in week:
                cell["archive_names"] = by_day.get(cell["date"], []) if cell["in_month"] else []
                month_names.update(cell["archive_names"])
        month["archive_names"] = sorted(month_names)
    return calendar
