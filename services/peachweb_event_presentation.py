"""Compact, public-only PeachWeb weekly event presentation.

No Flask or database dependency. This module accepts rows
from the restricted public event reader.
"""

from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from services.peachweb_event_schedule import format_week_heading


DAY_LABELS = ("Mon", "Tue", "Wed", "Thur", "Fri", "Sat", "Sun")


def _clock(value, *, suffix=False):
    hour = value.hour % 12 or 12
    minute = f":{value.minute:02d}" if value.minute else ""
    ending = (
        ("a" if value.hour < 12 else "p")
        if suffix else ""
    )
    return f"{hour}{minute}{ending}"


def _day_hours(row):
    """Format one scheduled day in its event timezone."""

    operating_date = row["operating_date"]
    opened = row["opens_at"]
    closed = row["closes_at"]

    if type(operating_date) is not date:
        raise ValueError("Invalid operating date.")

    if any(
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        for value in (opened, closed)
    ):
        raise ValueError("Timezone-aware hours required.")

    zone = ZoneInfo(row["timezone_name"])

    start = opened.astimezone(zone)
    end = closed.astimezone(zone)

    if (
        closed <= opened
        or start.date() != operating_date
    ):
        raise ValueError("Invalid operating hours.")

    overnight = end.date() > operating_date

    if overnight:
        days_later = (end.date() - operating_date).days
        return (
            f"{_clock(start, suffix=True)}–"
            f"{_clock(end, suffix=True)} "
            f"(+{days_later} day"
            f"{'s' if days_later != 1 else ''})"
        )

    return f"{_clock(start)}–{_clock(end)}"


def _compact_hours(daily_rows):
    """Combine consecutive dates having identical hours."""

    days = sorted(
        (row["operating_date"], _day_hours(row))
        for row in daily_rows
    )

    if not days:
        return ""

    groups = []
    first_day, last_day = days[0][0], days[0][0]
    current_hours = days[0][1]

    def add_group(first, last, hours):
        first_label = DAY_LABELS[first.weekday()]

        if first == last:
            label = first_label
        else:
            label = (
                first_label + "–" +
                DAY_LABELS[last.weekday()]
            )

        groups.append(f"{label}: {hours}")

    for day, hours in days[1:]:
        if (
            day == last_day + timedelta(days=1)
            and hours == current_hours
        ):
            last_day = day
        else:
            add_group(first_day, last_day, current_hours)
            first_day = last_day = day
            current_hours = hours

    add_group(first_day, last_day, current_hours)

    return " / ".join(groups)


def _directions_url(row):
    """Build a directions lookup using public address fields."""

    parts = (
        str(row.get("street_address") or "").strip(),
        str(row.get("city") or "").strip(),
        str(row.get("state") or "").strip(),
        str(row.get("zip_code") or "").strip(),
    )

    if not all(parts):
        return None

    address = f"{parts[0]}, {parts[1]}, {parts[2]} {parts[3]}"

    return (
        "https://www.google.com/maps/search/?"
        + urlencode({"api": "1", "query": address})
    )


def build_weekly_public_schedule(
    rows,
    windows,
    *,
    show_hours=True,
    show_directions=True,
):
    """Return populated Monday-Sunday groups for public display.

    Output intentionally excludes internal identifiers and
    administrative record fields.
    """

    if (
        len(windows) != 5
        or any(
            end != start + timedelta(days=6)
            or start.weekday() != 0
            for start, end in windows
        )
        or any(
            windows[index][0] != (
                windows[index - 1][0] + timedelta(days=7)
            )
            for index in range(1, 5)
        )
    ):
        raise ValueError("Five consecutive weeks required.")

    output = []

    for week_start, week_end in windows:
        by_event = {}
        seen_days = set()

        for row in rows:
            day = row["operating_date"]

            if not week_start <= day <= week_end:
                continue

            event_id = row["event_id"]
            identity = (event_id, day)

            if identity in seen_days:
                raise ValueError("Duplicate public event day.")

            seen_days.add(identity)

            if event_id not in by_event:
                by_event[event_id] = {
                    "sample": row,
                    "days": [],
                }

            by_event[event_id]["days"].append(row)

        if not by_event:
            continue

        events = []

        ordered = sorted(
            by_event.items(),
            key=lambda item: (
                min(
                    d["operating_date"]
                    for d in item[1]["days"]
                ),
                str(
                    item[1]["sample"]["event_name"]
                ).casefold(),
                item[0],
            ),
        )

        for _, record in ordered:
            sample = record["sample"]

            events.append({
                "name": str(
                    sample["event_name"] or ""
                ).strip(),
                "city": str(
                    sample["city"] or ""
                ).strip(),
                "hours": (
                    _compact_hours(record["days"])
                    if show_hours else ""
                ),
                "directions_url": (
                    _directions_url(sample)
                    if show_directions else None
                ),
            })

        output.append({
            "heading": format_week_heading(
                week_start, week_end
            ),
            "events": events,
        })

    return output
