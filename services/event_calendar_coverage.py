"""Advisory employee coverage analysis for PeachPOS events.

Input must be the normalized result of validate_event_payload().
This module performs no authorization, database operations,
or event-saving decisions.
"""


def _minutes(start, end):
    return int((end - start).total_seconds() / 60)


def _coverage_for_window(start, end, shifts, unit_id):
    intervals = []

    for shift in shifts:
        if shift["unit_id"] != unit_id:
            continue

        left = max(start, shift["starts_at"])
        right = min(end, shift["ends_at"])

        if left < right:
            intervals.append((left, right))

    intervals.sort()

    gaps = []
    cursor = start

    for left, right in intervals:
        if left > cursor:
            gaps.append({
                "starts_at": cursor.isoformat(),
                "ends_at": left.isoformat(),
                "minutes": _minutes(cursor, left),
            })

        if right > cursor:
            cursor = right

    if cursor < end:
        gaps.append({
            "starts_at": cursor.isoformat(),
            "ends_at": end.isoformat(),
            "minutes": _minutes(cursor, end),
        })

    required = _minutes(start, end)
    uncovered = sum(gap["minutes"] for gap in gaps)
    covered = required - uncovered

    if covered == 0:
        status = "no_staff"
    elif uncovered:
        status = "partial"
    else:
        status = "covered"

    return {
        "unit_id": unit_id,
        "status": status,
        "required_minutes": required,
        "covered_minutes": covered,
        "uncovered_minutes": uncovered,
        "gaps": gaps,
    }


def analyze_event_coverage(normalized):
    """Evaluate employee staffing throughout operating hours.

    Each assigned physical event unit is checked independently.
    An employee shift without a unit does not automatically
    provide coverage for any assigned unit.

    If an event day has no assigned units, shifts without units
    can provide event-wide staffing coverage.

    Overnight shifts from neighboring dates are included,
    and all interval comparisons use aware UTC timestamps.

    Returns serializable advisory results; no save restriction.
    """

    days = normalized["days"]

    all_shifts = [
        shift
        for day in days
        if day["operating"]
        for shift in day["shifts"]
    ]

    reports = []
    uncovered_unit_days = 0
    days_with_unassigned_shifts = 0

    for day in days:
        if not day["operating"]:
            continue

        start = day["opens_at"]
        end = day["closes_at"]
        equipment_ids = sorted(day["equipment_ids"])

        overlapping_unassigned = sum(
            1
            for shift in all_shifts
            if shift["unit_id"] is None
            and shift["starts_at"] < end
            and start < shift["ends_at"]
        )

        # Without physical equipment, evaluate overall event
        # staffing rather than truck-specific staffing.
        if not equipment_ids:
            unit_ids = [None]
            unassigned_count = 0
        else:
            unit_ids = equipment_ids
            unassigned_count = overlapping_unassigned

        if unassigned_count:
            days_with_unassigned_shifts += 1

        coverage = []

        for unit_id in unit_ids:
            report = _coverage_for_window(
                start, end, all_shifts, unit_id
            )

            if report["status"] != "covered":
                uncovered_unit_days += 1

            coverage.append(report)

        reports.append({
            "date": day["date"].isoformat(),
            "opens_at": start.isoformat(),
            "closes_at": end.isoformat(),
            "unit_coverage": coverage,
            "unassigned_shift_count": unassigned_count,
        })

    return {
        "days": reports,
        "uncovered_unit_days": uncovered_unit_days,
        "days_with_unassigned_shifts":
            days_with_unassigned_shifts,
        "advisory_only": True,
    }
