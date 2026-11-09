"""Read-only existing-event availability checks for PeachPOS.

Requires normalized, time-zone-aware event data.
The final save transaction must repeat these checks and
rely on PostgreSQL exclusion constraints for concurrency.
"""

from datetime import datetime
from services.event_calendar_time import intervals_overlap


class EventAvailabilityError(ValueError):
    """Equipment or employee is already booked."""


def _valid_interval(start, end):
    if not (
        isinstance(start, datetime)
        and isinstance(end, datetime)
        and start.tzinfo is not None
        and end.tzinfo is not None
        and start.utcoffset() is not None
        and end.utcoffset() is not None
        and start < end
    ):
        raise EventAvailabilityError(
            "Invalid time-zone-aware scheduling interval."
        )


def _proposed_intervals(normalized):
    equipment = {}
    employees = {}

    for day in normalized["days"]:
        if not day["operating"]:
            continue

        occupied_start = day["occupancy_start"]
        occupied_end = day["occupancy_end"]

        _valid_interval(occupied_start, occupied_end)

        for unit_id in day["equipment_ids"]:
            if type(unit_id) is not int or unit_id <= 0:
                raise EventAvailabilityError(
                    "Invalid equipment identifier."
                )

            equipment.setdefault(unit_id, []).append(
                (occupied_start, occupied_end)
            )

        for shift in day["shifts"]:
            employee_id = shift["employee_id"]
            start = shift["starts_at"]
            end = shift["ends_at"]

            if type(employee_id) is not int or employee_id <= 0:
                raise EventAvailabilityError(
                    "Invalid employee identifier."
                )

            _valid_interval(start, end)

            employees.setdefault(employee_id, []).append(
                (start, end)
            )

    return equipment, employees


def _check_saved_intervals(cursor, sql, groups, spa_id, label):
    if not groups:
        return 0

    intervals = [
        interval
        for resource_intervals in groups.values()
        for interval in resource_intervals
    ]

    earliest = min(start for start, _ in intervals)
    latest = max(end for _, end in intervals)

    cursor.execute(
        sql,
        (spa_id, sorted(groups), latest, earliest),
    )

    examined = 0

    for resource_id, booked_start, booked_end in cursor.fetchall():
        examined += 1
        _valid_interval(booked_start, booked_end)

        for proposed_start, proposed_end in groups.get(
            int(resource_id), ()
        ):
            if intervals_overlap(
                proposed_start,
                proposed_end,
                booked_start,
                booked_end,
            ):
                raise EventAvailabilityError(
                    f"{label} is already scheduled during "
                    "the proposed time."
                )

    return examined


def validate_existing_event_availability(
    cursor, normalized, spa_id
):
    """Check existing ACTIVE reservations across the business.

    No business_unit_id restriction is applied: the same
    employee or physical equipment cannot be double-booked
    in another workspace within the same business.

    This is a preflight check, not concurrency protection.
    """

    if type(spa_id) is not int or spa_id <= 0:
        raise EventAvailabilityError("Invalid business scope.")

    equipment, employees = _proposed_intervals(normalized)

    unit_sql = """
        SELECT event_unit_id,
               assigned_start_at,
               assigned_end_at
        FROM event_calendar_unit_assignments
        WHERE spa_id = %s
          AND event_unit_id = ANY(%s::bigint[])
          AND is_active = TRUE
          AND assigned_start_at < %s
          AND assigned_end_at > %s
    """

    employee_sql = """
        SELECT employee_id,
               shift_start_at,
               shift_end_at
        FROM event_calendar_employee_assignments
        WHERE spa_id = %s
          AND employee_id = ANY(%s::integer[])
          AND is_active = TRUE
          AND shift_start_at < %s
          AND shift_end_at > %s
    """

    units_examined = _check_saved_intervals(
        cursor, unit_sql, equipment, spa_id, "Equipment"
    )

    shifts_examined = _check_saved_intervals(
        cursor, employee_sql, employees, spa_id, "Employee"
    )

    return {
        "availability_validated": True,
        "equipment_resources_checked": len(equipment),
        "employee_resources_checked": len(employees),
        "existing_unit_reservations_examined": units_examined,
        "existing_employee_shifts_examined": shifts_examined,
    }
