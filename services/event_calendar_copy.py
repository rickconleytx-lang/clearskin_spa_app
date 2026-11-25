"""Build a NEW PeachPOS event draft from a saved, workspace-scoped event.

The caller must first authorize the admin and read the source with
load_event_edit_payload in a consistent read-only transaction.
This module performs no database operations and NEVER changes the source.
The result uses the existing /events/save payload format (no source event ID).
"""

from datetime import date, timedelta
import copy
import re


class EventCopyInvalid(ValueError):
    """The requested copy cannot safely be generated."""


SECTION_DEFAULTS = {
    "event_details": True,
    "location": True,
    "daily_hours": True,
    "equipment": True,
    "notes": True,
    "custom_fields": True,
    "contacts": False,
    "employees": False,
    "permits": False,
}

_LOCATION_FIELDS = (
    "venue_name", "street_address", "address_line2", "city", "county",
    "state", "zip_code", "parking_setup_location",
)
_CONTACT_FIELDS = ("contact_name", "contact_phone", "contact_email")
_NOTE_FIELDS = ("notes_1", "notes_2")


def _date(value, label):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise EventCopyInvalid(f"{label} must be a YYYY-MM-DD date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EventCopyInvalid(f"{label} is not a valid date.") from exc


def _copy_sections(sections):
    if sections is None:
        return SECTION_DEFAULTS.copy()
    if type(sections) is not dict or set(sections) != set(SECTION_DEFAULTS):
        raise EventCopyInvalid("Invalid Copy Event section selection.")
    if any(type(v) is not bool for v in sections.values()):
        raise EventCopyInvalid("Copy Event selections must be true or false.")
    return sections.copy()


def build_event_copy_draft(
    source, *, target_start_date=None, target_end_date=None, sections=None
):
    """Return a fresh Create Event payload with shifted daily rows.

    New event dates default to exactly seven calendar days later.
    Explicit dates may shorten or extend the span (up to 366 days): existing
    days map by ordinal offset; added days are non-operating. Checked
    resources and shifts are only proposed: /events/validate and /events/save
    MUST re-check live ownership and scheduling conflicts before saving.
    """
    selected = _copy_sections(sections)
    if type(source) is not dict or type(source.get("event")) is not dict:
        raise EventCopyInvalid("Saved event data is unavailable.")
    if type(source.get("event_id")) is not int or source["event_id"] <= 0:
        raise EventCopyInvalid("Saved event identity is invalid.")
    if type(source.get("event_revision")) is not int or source["event_revision"] <= 0:
        raise EventCopyInvalid("Saved event revision is invalid.")

    saved = source["event"]
    original_start = _date(saved.get("start_date"), "Original start date")
    original_end = _date(saved.get("end_date"), "Original end date")
    original_length = (original_end - original_start).days + 1
    if not 1 <= original_length <= 366:
        raise EventCopyInvalid("Saved event date range is invalid.")

    if target_start_date is None:
        if target_end_date is not None:
            raise EventCopyInvalid("Select a start date with the end date.")
        new_start = original_start + timedelta(days=7)
    else:
        new_start = _date(target_start_date, "New start date")

    if target_end_date is None:
        new_end = new_start + timedelta(days=original_length - 1)
    else:
        new_end = _date(target_end_date, "New end date")

    new_length = (new_end - new_start).days + 1
    if not (2000 <= new_start.year <= 2100 and 2000 <= new_end.year <= 2100):
        raise EventCopyInvalid("Event dates must be between 2000 and 2100.")
    if not 1 <= new_length <= 366:
        raise EventCopyInvalid("New event must span 1–366 days.")

    if type(source.get("days")) is not list or len(source["days"]) != original_length:
        raise EventCopyInvalid("Saved operating-day data is incomplete.")
    by_date = {}
    for item in source["days"]:
        if type(item) is not dict:
            raise EventCopyInvalid("Invalid saved operating-day data.")
        key = _date(item.get("date"), "Original operating date")
        if key in by_date or not original_start <= key <= original_end:
            raise EventCopyInvalid("Duplicate or out-of-range original day.")
        if type(item.get("operating")) is not bool:
            raise EventCopyInvalid("Invalid original operating-day status.")
        if type(item.get("equipment_ids")) is not list or type(item.get("shifts")) is not list:
            raise EventCopyInvalid("Invalid original assignments.")
        by_date[key] = item
    if len(by_date) != original_length:
        raise EventCopyInvalid("Saved event is missing an operating day.")

    # Strip original identity, revision, status, and public visibility.
    event = {
        "name": saved.get("name", "") if selected["event_details"] else "",
        "start_date": new_start.isoformat(),
        "end_date": new_end.isoformat(),
        "status": "scheduled",
        "include_on_peachweb": False,
        "permits_obtained": (
            saved.get("permits_obtained") is True if selected["permits"] else False
        ),
        "public_description": (
            saved.get("public_description", "") if selected["event_details"] else ""
        ),
    }
    for field in _LOCATION_FIELDS:
        event[field] = saved.get(field, "") if selected["location"] else ""
    for field in _CONTACT_FIELDS:
        event[field] = saved.get(field, "") if selected["contacts"] else ""
    for field in _NOTE_FIELDS:
        event[field] = saved.get(field, "") if selected["notes"] else ""

    custom = source.get("custom_values", {})
    if type(custom) is not dict:
        raise EventCopyInvalid("Invalid saved custom fields.")
    if not set(custom).issubset({"1", "2", "3"}):
        raise EventCopyInvalid("Unexpected saved custom field.")
    custom_values = {
        slot: copy.deepcopy(custom.get(slot, "")) if selected["custom_fields"] else ""
        for slot in ("1", "2", "3")
    }

    days = []
    for index in range(new_length):
        new_date = new_start + timedelta(days=index)
        original_day = by_date.get(original_start + timedelta(days=index))
        operating = bool(original_day and original_day["operating"])
        copy_hours = bool(operating and selected["daily_hours"])
        proposed_equipment = (
            copy.deepcopy(original_day["equipment_ids"])
            if copy_hours and selected["equipment"] else []
        )
        shifts = (
            copy.deepcopy(original_day["shifts"])
            if copy_hours and selected["employees"] else []
        )
        # Without the corresponding truck assignment, shift remains unassigned.
        if shifts and not selected["equipment"]:
            for shift in shifts:
                if type(shift) is not dict:
                    raise EventCopyInvalid("Invalid original employee shift.")
                shift["equipment_id"] = None
        day = {
            "date": new_date.isoformat(),
            "operating": operating,
            "opens": original_day.get("opens") if copy_hours else None,
            "closes": original_day.get("closes") if copy_hours else None,
            "closes_next_day": (
                original_day.get("closes_next_day") is True if copy_hours else False
            ),
            "setup": original_day.get("setup") if copy_hours else None,
            "breakdown": original_day.get("breakdown") if copy_hours else None,
            "notes": (
                original_day.get("notes", "")
                if operating and selected["notes"] else ""
            ),
            "equipment_ids": proposed_equipment,
            "shifts": shifts,
        }
        days.append(day)

    return {"event": event, "custom_values": custom_values, "days": days}
