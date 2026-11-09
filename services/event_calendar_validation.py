"""Validate a PeachPOS event submission without database writes.

Reference ownership, authorization, and conflicts with saved
events must also be checked inside the eventual save transaction.
"""

from datetime import datetime, timedelta
import re

from services.event_calendar_time import (
    EventTimeError,
    event_time_interval,
    intervals_overlap,
    parse_event_date,
    parse_event_time,
    resolve_local_time,
)


class EventValidationError(ValueError):
    pass


FIELD_LIMITS = {
    "name": (200, True),
    "venue_name": (200, True),
    "street_address": (255, True),
    "address_line2": (255, False),
    "city": (120, True),
    "county": (120, False),
    "state": (80, True),
    "zip_code": (20, True),
    "parking_setup_location": (5000, False),
    "contact_name": (150, False),
    "contact_phone": (40, False),
    "contact_email": (254, False),
    "public_description": (5000, False),
    "notes_1": (5000, False),
    "notes_2": (5000, False),
}


def read_text(record, key, maximum, required=False):
    value = record.get(key, "")

    if not isinstance(value, str):
        raise EventValidationError(f"{key}: Expected text.")

    value = value.strip()

    if len(value) > maximum:
        raise EventValidationError(f"{key}: Text is too long.")

    if any(
        (ord(char) < 32 and char not in "\n\t")
        or ord(char) == 127
        for char in value
    ):
        raise EventValidationError(
            f"{key}: Invalid control character."
        )

    if required and not value:
        raise EventValidationError(f"{key}: Required.")

    return value


def read_bool(record, key, default=False):
    value = record.get(key, default)

    if type(value) is not bool:
        raise EventValidationError(
            f"{key}: Expected true or false."
        )

    return value


def read_id(value, label, optional=False, maximum=2147483647):
    if optional and (value is None or value == ""):
        return None

    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(
        r"[0-9]{1,19}", value
    ):
        number = int(value)
    else:
        raise EventValidationError(
            f"{label}: Invalid identifier."
        )

    if not 1 <= number <= maximum:
        raise EventValidationError(
            f"{label}: Identifier out of range."
        )

    return number


def local_instant(day, clock, timezone_name, day_offset=0):
    try:
        local = datetime.combine(
            day + timedelta(days=day_offset),
            parse_event_time(clock),
        )
        return resolve_local_time(local, timezone_name)
    except EventTimeError as exc:
        raise EventValidationError(str(exc)) from exc


def validate_event_payload(payload, timezone_name):
    """Return normalized event data, including UTC timestamps.

    timezone_name must come from trusted business settings,
    never from the submitted JSON.
    """

    if type(payload) is not dict or set(payload) != {
        "event", "custom_values", "days"
    }:
        raise EventValidationError(
            "Invalid event submission structure."
        )

    raw_event = payload["event"]
    raw_custom = payload["custom_values"]
    raw_days = payload["days"]

    if type(raw_event) is not dict:
        raise EventValidationError("Invalid event information.")

    if type(raw_custom) is not dict:
        raise EventValidationError("Invalid custom fields.")

    if type(raw_days) is not list:
        raise EventValidationError("Invalid operating days.")

    try:
        start = parse_event_date(raw_event.get("start_date"))
        end = parse_event_date(raw_event.get("end_date"))
    except EventTimeError as exc:
        raise EventValidationError(str(exc)) from exc

    if start.year < 2000 or end.year > 2100:
        raise EventValidationError(
            "Event dates must be between 2000 and 2100."
        )

    day_count = (end - start).days + 1

    if not 1 <= day_count <= 366:
        raise EventValidationError(
            "Event date range must contain 1–366 days."
        )

    if len(raw_days) != day_count:
        raise EventValidationError(
            "Every date in the event range must be included."
        )

    event = {}

    for key, (limit, required) in FIELD_LIMITS.items():
        event[key] = read_text(
            raw_event, key, limit, required
        )

    status = read_text(raw_event, "status", 20, True)

    if status not in {
        "scheduled", "confirmed", "cancelled", "completed"
    }:
        raise EventValidationError("Invalid event status.")

    event.update({
        "start_date": start,
        "end_date": end,
        "status": status,
        "include_on_peachweb": read_bool(
            raw_event, "include_on_peachweb"
        ),
        "permits_obtained": read_bool(
            raw_event, "permits_obtained"
        ),
    })

    email = event["contact_email"]

    if email and not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        raise EventValidationError("Invalid contact email.")

    if not set(raw_custom).issubset({"1", "2", "3"}):
        raise EventValidationError(
            "Only three custom fields are supported."
        )

    custom_values = {
        slot: read_text(raw_custom, slot, 5000)
        for slot in ("1", "2", "3")
    }

    normalized_days = []
    seen_dates = set()
    employee_intervals = {}
    equipment_intervals = {}
    total_shifts = 0
    operating_days = 0

    for raw in raw_days:
        if type(raw) is not dict:
            raise EventValidationError("Invalid daily schedule.")

        try:
            date = parse_event_date(raw.get("date"))
        except EventTimeError as exc:
            raise EventValidationError(str(exc)) from exc

        if date < start or date > end or date in seen_dates:
            raise EventValidationError(
                "Duplicate or out-of-range operating date."
            )

        seen_dates.add(date)
        operating = read_bool(raw, "operating")

        equipment = raw.get("equipment_ids", [])
        shifts = raw.get("shifts", [])

        if type(equipment) is not list or len(equipment) > 50:
            raise EventValidationError(
                "Invalid daily equipment selection."
            )

        if type(shifts) is not list or len(shifts) > 50:
            raise EventValidationError(
                "Invalid daily employee shifts."
            )

        if not operating:
            if equipment or shifts:
                raise EventValidationError(
                    "Non-operating days cannot have assignments."
                )

            normalized_days.append({
                "date": date,
                "operating": False,
                "equipment_ids": [],
                "shifts": [],
            })
            continue

        operating_days += 1

        overnight = read_bool(raw, "closes_next_day")

        try:
            opens_at, closes_at = event_time_interval(
                date.isoformat(),
                raw.get("opens"),
                raw.get("closes"),
                overnight,
                timezone_name,
            )
            open_clock = parse_event_time(raw["opens"])
            close_clock = parse_event_time(raw["closes"])
        except EventTimeError as exc:
            raise EventValidationError(
                f"{date}: {exc}"
            ) from exc

        setup_at = None
        breakdown_at = None

        setup = raw.get("setup")
        breakdown = raw.get("breakdown")

        if setup not in ("", None):
            try:
                setup_clock = parse_event_time(setup)
            except EventTimeError as exc:
                raise EventValidationError(
                    f"{date}: Invalid setup time: {exc}"
                ) from exc
            setup_at = local_instant(
                date, setup, timezone_name,
                -1 if setup_clock > open_clock else 0
            )

            if not (
                timedelta(0)
                <= opens_at - setup_at
                <= timedelta(hours=24)
            ):
                raise EventValidationError(
                    f"{date}: Invalid setup time."
                )

        if breakdown not in ("", None):
            try:
                breakdown_clock = parse_event_time(breakdown)
            except EventTimeError as exc:
                raise EventValidationError(
                    f"{date}: Invalid breakdown time: {exc}"
                ) from exc
            offset = int(overnight)

            if breakdown_clock < close_clock:
                offset += 1

            breakdown_at = local_instant(
                date, breakdown, timezone_name, offset
            )

            if not (
                timedelta(0)
                <= breakdown_at - closes_at
                <= timedelta(hours=24)
            ):
                raise EventValidationError(
                    f"{date}: Invalid breakdown time."
                )

        occupancy_start = setup_at or opens_at
        occupancy_end = breakdown_at or closes_at

        equipment_ids = [
            read_id(
                value, "Equipment",
                maximum=9223372036854775807
            )
            for value in equipment
        ]

        if len(set(equipment_ids)) != len(equipment_ids):
            raise EventValidationError(
                f"{date}: Equipment selected more than once."
            )

        for unit_id in equipment_ids:
            equipment_intervals.setdefault(
                unit_id, []
            ).append((occupancy_start, occupancy_end))

        normalized_shifts = []

        for shift in shifts:
            if type(shift) is not dict:
                raise EventValidationError(
                    "Invalid employee shift."
                )

            employee_id = read_id(
                shift.get("employee_id"), "Employee"
            )
            unit_id = read_id(
                shift.get("equipment_id"),
                "Shift equipment",
                optional=True,
                maximum=9223372036854775807,
            )

            if unit_id is not None and unit_id not in equipment_ids:
                raise EventValidationError(
                    f"{date}: Shift equipment is not "
                    "assigned to that operating day."
                )

            try:
                shift_start, shift_end = event_time_interval(
                    date.isoformat(),
                    shift.get("starts"),
                    shift.get("ends"),
                    read_bool(shift, "ends_next_day"),
                    timezone_name,
                )
            except EventTimeError as exc:
                raise EventValidationError(
                    f"{date}: Invalid employee shift: {exc}"
                ) from exc

            employee_intervals.setdefault(
                employee_id, []
            ).append((shift_start, shift_end))

            normalized_shifts.append({
                "employee_id": employee_id,
                "unit_id": unit_id,
                "starts_at": shift_start,
                "ends_at": shift_end,
                "role": read_text(shift, "role", 100),
                "notes": read_text(shift, "notes", 5000),
            })

            total_shifts += 1

            if total_shifts > 2000:
                raise EventValidationError(
                    "Too many employee shifts in one event."
                )

        normalized_days.append({
            "date": date,
            "operating": True,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "setup_at": setup_at,
            "breakdown_at": breakdown_at,
            "notes": read_text(raw, "notes", 5000),
            "equipment_ids": equipment_ids,
            "shifts": normalized_shifts,
            "occupancy_start": occupancy_start,
            "occupancy_end": occupancy_end,
        })

    if operating_days == 0:
        raise EventValidationError(
            "At least one operating day is required."
        )

    def verify_overlaps(groups, resource_name):
        for intervals in groups.values():
            intervals.sort(key=lambda interval: interval[0])

            for previous, current in zip(
                intervals, intervals[1:]
            ):
                if intervals_overlap(
                    previous[0], previous[1],
                    current[0], current[1]
                ):
                    raise EventValidationError(
                        f"Overlapping {resource_name} "
                        "assignments in this event."
                    )

    verify_overlaps(
        employee_intervals, "employee"
    )
    verify_overlaps(
        equipment_intervals, "equipment"
    )

    normalized_days.sort(key=lambda day: day["date"])

    return {
        "event": event,
        "custom_values": custom_values,
        "days": normalized_days,
        "timezone_name": timezone_name,
    }
