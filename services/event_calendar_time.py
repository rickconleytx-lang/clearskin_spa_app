"""Strict local-time conversion for PeachPOS event scheduling.

Pure validation helpers. No database access or writes.
The caller must obtain the timezone from trusted business settings.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re


class EventTimeError(ValueError):
    """Invalid or ambiguous event schedule time."""


def parse_event_date(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value
    ):
        raise EventTimeError("Invalid event date format.")

    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise EventTimeError("Invalid event date.") from exc

    if result.isoformat() != value:
        raise EventTimeError("Invalid event date.")

    return result


def parse_event_time(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", value
    ):
        raise EventTimeError(
            "Time must use the 24-hour HH:MM format."
        )

    hour, minute = map(int, value.split(":"))
    return time(hour, minute)


def resolve_local_time(local_datetime, timezone_name):
    """Convert a local wall time into a unique UTC instant.

    Reject missing spring-forward times and ambiguous
    fall-back times instead of silently guessing.
    """

    if not isinstance(timezone_name, str) or not timezone_name:
        raise EventTimeError("Business time zone is required.")

    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise EventTimeError(
            "Business time zone is not recognized."
        ) from exc

    candidates = set()

    for fold in (0, 1):
        aware = local_datetime.replace(
            tzinfo=zone,
            fold=fold
        )

        utc = aware.astimezone(timezone.utc)

        restored = utc.astimezone(zone).replace(
            tzinfo=None
        )

        if restored == local_datetime:
            candidates.add(utc)

    if not candidates:
        raise EventTimeError(
            "This local time does not exist because of "
            "a daylight-saving time change."
        )

    if len(candidates) > 1:
        raise EventTimeError(
            "This local time occurs twice because of "
            "a daylight-saving time change. "
            "Choose an unambiguous time."
        )

    return candidates.pop()


def event_time_interval(
    operating_date,
    start_time,
    end_time,
    ends_next_day,
    timezone_name
):
    """Return (UTC start, UTC end) for an event or shift.

    The end is exclusive; adjacent intervals do not overlap.
    A civil-time interval must be greater than 0 and
    no longer than 24 hours.
    """

    day = parse_event_date(operating_date)
    starts = parse_event_time(start_time)
    ends = parse_event_time(end_time)

    if not isinstance(ends_next_day, bool):
        raise EventTimeError(
            "Overnight setting must be true or false."
        )

    start_local = datetime.combine(day, starts)

    end_local = datetime.combine(
        day + timedelta(days=1 if ends_next_day else 0),
        ends
    )

    duration = end_local - start_local

    if (
        duration <= timedelta(0)
        or duration > timedelta(hours=24)
    ):
        raise EventTimeError(
            "Closing time must follow opening time "
            "and be within 24 local hours."
        )

    start_utc = resolve_local_time(
        start_local, timezone_name
    )
    end_utc = resolve_local_time(
        end_local, timezone_name
    )

    if end_utc <= start_utc:
        raise EventTimeError(
            "Schedule must have a positive elapsed duration."
        )

    return start_utc, end_utc


def intervals_overlap(start_a, end_a, start_b, end_b):
    """Half-open interval comparison, allowing adjacency."""

    return start_a < end_b and start_b < end_a
