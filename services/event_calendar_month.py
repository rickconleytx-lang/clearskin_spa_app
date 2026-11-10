"""Presentation model for the read-only PeachPOS Month calendar."""

from calendar import Calendar, month_name
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.event_calendar_read import safe_calendar_color


def format_event_clock(value, timezone_name):
    """Display an aware PostgreSQL timestamp in business local time."""
    if not isinstance(value, datetime):
        return ""

    if value.tzinfo is not None and timezone_name:
        try:
            value = value.astimezone(ZoneInfo(timezone_name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            pass

    return value.strftime("%I:%M %p").lstrip("0")


def relative_luminance(hex_color):
    """Calculate WCAG-style relative luminance for an RGB color."""
    color = safe_calendar_color(hex_color)

    def linearize(channel):
        value = channel / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red = linearize(int(color[1:3], 16))
    green = linearize(int(color[3:5], 16))
    blue = linearize(int(color[5:7], 16))

    return (
        0.2126 * red
        + 0.7152 * green
        + 0.0722 * blue
    )


def readable_text_color(hex_color):
    """Choose whichever text color has greater contrast."""
    background = relative_luminance(hex_color)

    dark = relative_luminance("#17212B")
    white = relative_luminance("#FFFFFF")

    dark_contrast = (
        (max(background, dark) + 0.05)
        / (min(background, dark) + 0.05)
    )

    white_contrast = (
        (max(background, white) + 0.05)
        / (min(background, white) + 0.05)
    )

    return (
        "#17212B"
        if dark_contrast >= white_contrast
        else "#FFFFFF"
    )


def build_month_view(rows, year, month, today=None):
    """Organize operating-day assignments into a Sunday-first grid.

    Each event/unit combination appears on each operating date.
    Non-operating dates are intentionally omitted from event chips.
    """
    if (
        type(year) is not int
        or type(month) is not int
        or not 2000 <= year <= 2100
        or not 1 <= month <= 12
    ):
        raise ValueError("Invalid Event Calendar month.")

    if today is None:
        today = date.today()

    weeks = Calendar(firstweekday=6).monthdatescalendar(year, month)
    first = weeks[0][0]
    last = weeks[-1][-1]

    by_date = defaultdict(list)
    seen = set()

    for row in rows:
        operating_date = row.get("operating_date")

        if (
            row.get("daily_schedule_id") is None
            or not isinstance(operating_date, date)
            or isinstance(operating_date, datetime)
            or not first <= operating_date <= last
        ):
            continue

        key = (
            operating_date,
            row.get("event_id"),
            row.get("event_unit_id"),
        )

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

        hours = (
            f"{opening} – {closing}"
            if opening and closing else "Hours not available"
        )

        by_date[operating_date].append({
            "event_id": row.get("event_id"),
            "name": row.get("event_name") or "Untitled Event",
            "unit": row.get("unit_name") or "No truck assigned",
            "color": color,
            "text_color": readable_text_color(color),
            "hours": hours,
            "status": row.get("event_status") or "",
        })

    display_weeks = []

    for week in weeks:
        display_week = []

        for day in week:
            display_week.append({
                "date": day,
                "iso": day.isoformat(),
                "number": day.day,
                "in_month": day.month == month,
                "today": day == today,
                "entries": by_date[day],
            })

        display_weeks.append(display_week)

    prev_year, prev_month = (
        (year - 1, 12) if month == 1 else (year, month - 1)
    )
    next_year, next_month = (
        (year + 1, 1) if month == 12 else (year, month + 1)
    )

    return {
        "year": year,
        "month": month,
        "label": f"{month_name[month]} {year}",
        "weeks": display_weeks,
        "entry_count": sum(
            len(item["entries"])
            for week in display_weeks
            for item in week
            if item["in_month"]
        ),
        "previous_year": prev_year,
        "previous_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
    }
