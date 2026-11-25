"""Pure Sunday-first weekly presentation model for PeachPOS Event Calendar.

Reuses list_event_calendar_rows() for precisely seven dates. The caller owns
workspace scoping, read-only DB transaction, and connection management.
No SQL, database writes, permission decisions, or HTTP behavior lives here.
"""

from calendar import day_abbr, month_name
from datetime import date, datetime, timedelta

from services.event_calendar_month import (
    format_event_clock,
    readable_text_color,
)
from services.event_calendar_read import safe_calendar_color


class EventWeekViewError(ValueError):
    """Invalid weekly calendar presentation input."""


def week_bounds(anchor):
    """Return inclusive Sunday/Saturday window containing anchor."""
    if type(anchor) is not date or not 2000 <= anchor.year <= 2100:
        raise EventWeekViewError("Invalid Week Calendar date.")
    first = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    return first, first + timedelta(days=6)


def _label(first, last):
    if first.year == last.year and first.month == last.month:
        return f"{month_name[first.month]} {first.day}–{last.day}, {first.year}"
    if first.year == last.year:
        return (f"{month_name[first.month]} {first.day} – "
                f"{month_name[last.month]} {last.day}, {last.year}")
    return (f"{month_name[first.month]} {first.day}, {first.year} – "
            f"{month_name[last.month]} {last.day}, {last.year}")


def _location(row):
    city = str(row.get("city") or "").strip()
    state = str(row.get("state") or "").strip()
    return ", ".join(part for part in (city, state) if part)


def _clock_sort(value):
    """Sort visible start times consistently with displayed business time."""
    if not value:
        return (24, 0)
    try:
        parsed = datetime.strptime(value, "%I:%M %p")
        return (parsed.hour, parsed.minute)
    except (ValueError, TypeError):
        return (24, 0)


def build_week_view(rows, anchor, today=None):
    """Build seven day cells, one per operating event/unit assignment.

    Three trucks on the same event/date produce three visible cards but only
    one distinct event. Non-operating event days are not displayed. Cancelled
    assignments remain visible and marked as in existing Month View.
    """
    first, last = week_bounds(anchor)
    if today is None:
        today = date.today()
    if type(today) is not date:
        raise EventWeekViewError("Invalid current date.")
    if rows is None:
        raise EventWeekViewError("Missing weekly calendar rows.")

    by_date = {first + timedelta(days=i): [] for i in range(7)}
    seen = set()
    for row in rows:
        if type(row) is not dict:
            raise EventWeekViewError("Invalid weekly calendar row.")
        operating_date = row.get("operating_date")
        if (type(operating_date) is not date
                or not first <= operating_date <= last
                or row.get("daily_schedule_id") is None):
            continue
        event_id = row.get("event_id")
        unit_id = row.get("event_unit_id")
        if type(event_id) is not int or event_id <= 0:
            raise EventWeekViewError("Invalid weekly event identifier.")
        if unit_id is not None and (type(unit_id) is not int or unit_id <= 0):
            raise EventWeekViewError("Invalid weekly event unit.")

        key = (operating_date, event_id, unit_id)
        if key in seen:
            continue
        seen.add(key)

        color = safe_calendar_color(row.get("calendar_color"))
        opening = format_event_clock(
            row.get("opens_at"), row.get("timezone_name")
        )
        closing = format_event_clock(
            row.get("closes_at"), row.get("timezone_name")
        )
        hours = (f"{opening} – {closing}"
                 if opening and closing else "Hours not available")
        status = str(row.get("event_status") or "").strip()
        by_date[operating_date].append({
            "event_id": event_id,
            "event_unit_id": unit_id,
            "name": str(row.get("event_name") or "Untitled Event"),
            "unit": str(row.get("unit_name") or "No truck assigned"),
            "venue": str(row.get("venue_name") or "").strip(),
            "location": _location(row),
            "color": color,
            "text_color": readable_text_color(color),
            "hours": hours,
            "status": status,
            "is_cancelled": status.lower() == "cancelled",
            "_start_sort": _clock_sort(opening),
        })

    days = []
    for operating_date, entries in by_date.items():
        entries.sort(key=lambda item: (
            item["_start_sort"], item["unit"].casefold(),
            item["name"].casefold(), item["event_id"]
        ))
        for item in entries:
            del item["_start_sort"]
        days.append({
            "date": operating_date,
            "iso": operating_date.isoformat(),
            "number": operating_date.day,
            "weekday": day_abbr[(operating_date.weekday())],
            "label": operating_date.strftime("%A, %B %d, %Y"),
            "today": operating_date == today,
            "entries": entries,
            "event_count": len({item["event_id"] for item in entries}),
            "assignment_count": len(entries),
            "active_assignment_count": sum(
                not item["is_cancelled"] for item in entries
            ),
        })

    prev = first - timedelta(days=7)
    following = first + timedelta(days=7)
    return {
        "anchor_date": anchor,
        "week_start": first,
        "week_end": last,
        "label": _label(first, last),
        "days": days,
        "entry_count": sum(day["assignment_count"] for day in days),
        "event_day_count": sum(day["event_count"] for day in days),
        "active_assignment_count": sum(
            day["active_assignment_count"] for day in days
        ),
        "previous_date": prev if prev.year >= 2000 else None,
        "next_date": following if following.year <= 2100 else None,
        "year": anchor.year,
        "month": anchor.month,
    }
