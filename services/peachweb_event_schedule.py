"""PeachWeb public Events & Locations calendar utilities.

Five rolling Monday-Sunday weeks in the business's
configured local timezone. No database or Flask dependency.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


PUBLIC_WEEK_COUNT = 5


def five_week_windows(timezone_name, *, now=None):
    """Return five consecutive inclusive Monday-Sunday windows."""

    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise ValueError("Business timezone is required.")

    zone = ZoneInfo(timezone_name)

    instant = now if now is not None else datetime.now(timezone.utc)

    if (
        not isinstance(instant, datetime)
        or instant.tzinfo is None
        or instant.utcoffset() is None
    ):
        raise ValueError("An aware datetime is required.")

    today = instant.astimezone(zone).date()

    first_monday = today - timedelta(days=today.weekday())

    return tuple(
        (
            first_monday + timedelta(weeks=index),
            first_monday + timedelta(weeks=index, days=6),
        )
        for index in range(PUBLIC_WEEK_COUNT)
    )


def format_week_heading(start_date, end_date):
    """Format an inclusive Monday-Sunday public heading."""

    if (
        start_date.weekday() != 0
        or end_date != start_date + timedelta(days=6)
    ):
        raise ValueError("A Monday-Sunday week is required.")

    if (
        start_date.year == end_date.year
        and start_date.month == end_date.month
    ):
        return f"{start_date:%B} {start_date.day}–{end_date.day}"

    if start_date.year == end_date.year:
        return (
            f"{start_date:%B} {start_date.day} – "
            f"{end_date:%B} {end_date.day}"
        )

    return (
        f"{start_date:%B} {start_date.day}, {start_date.year} – "
        f"{end_date:%B} {end_date.day}, {end_date.year}"
    )
