import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.event_calendar_availability import (
    EventAvailabilityError,
    validate_existing_event_availability,
)

START = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=8)


def draft(
    unit=1, employee=43, start=START, end=END,
    occupancy_start=None
):
    return {
        "days": [{
            "operating": True,
            "equipment_ids": [] if unit is None else [unit],
            "occupancy_start": (
                start if occupancy_start is None
                else occupancy_start
            ),
            "occupancy_end": end,
            "shifts": [] if employee is None else [{
                "employee_id": employee,
                "starts_at": start,
                "ends_at": end,
            }],
        }]
    }


class FakeCursor:
    # Stored tuples:
    # (spa_id, workspace_id, resource_id, start, end, active)

    def __init__(self, units=(), employees=()):
        self.units = list(units)
        self.employees = list(employees)
        self.rows = []
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

        assert "WHERE spa_id = %s" in sql
        assert "is_active = TRUE" in sql
        assert "business_unit_id" not in sql

        if "FROM event_calendar_unit_assignments" in sql:
            records = self.units
            assert "ANY(%s::bigint[])" in sql

        elif "FROM event_calendar_employee_assignments" in sql:
            records = self.employees
            assert "ANY(%s::integer[])" in sql

        else:
            raise AssertionError("Unexpected SQL query.")

        spa_id, resource_ids, latest, earliest = params

        self.rows = [
            (resource_id, start, end)
            for business, workspace, resource_id,
                start, end, active in records
            if business == spa_id
            and resource_id in resource_ids
            and active
            and start < latest
            and end > earliest
        ]

    def fetchall(self):
        return self.rows


def booked(
    resource_id=1, start=START, end=END,
    spa=44, workspace=41, active=True
):
    return (spa, workspace, resource_id, start, end, active)


class EventAvailabilityTests(unittest.TestCase):

    def check(self, cursor, proposal=None, spa=44):
        return validate_existing_event_availability(
            cursor, draft() if proposal is None else proposal, spa
        )

    def rejected(self, cursor, proposal=None, spa=44):
        with self.assertRaises(EventAvailabilityError):
            self.check(cursor, proposal, spa)

    def test_no_resources(self):
        cursor = FakeCursor()
        result = self.check(
            cursor, draft(unit=None, employee=None)
        )
        self.assertTrue(result["availability_validated"])
        self.assertEqual(len(cursor.calls), 0)

    def test_available_resources(self):
        cursor = FakeCursor()
        result = self.check(cursor)
        self.assertEqual(result["equipment_resources_checked"], 1)
        self.assertEqual(result["employee_resources_checked"], 1)
        self.assertEqual(len(cursor.calls), 2)

    def test_overlapping_truck_rejected(self):
        cursor = FakeCursor(units=[booked()])
        self.rejected(cursor)

    def test_adjacent_truck_booking_allowed(self):
        cursor = FakeCursor(units=[
            booked(start=END, end=END + timedelta(hours=2))
        ])
        self.check(cursor)

    def test_overlapping_employee_rejected(self):
        cursor = FakeCursor(employees=[
            booked(resource_id=43)
        ])
        self.rejected(cursor)

    def test_adjacent_employee_shift_allowed(self):
        cursor = FakeCursor(employees=[
            booked(
                resource_id=43,
                start=END,
                end=END + timedelta(hours=2),
            )
        ])
        self.check(cursor)

    def test_other_resources_do_not_conflict(self):
        cursor = FakeCursor(
            units=[booked(resource_id=2)],
            employees=[booked(resource_id=44)],
        )
        self.check(cursor)

    def test_other_workspace_truck_conflicts(self):
        cursor = FakeCursor(units=[
            booked(workspace=42)
        ])
        self.rejected(cursor)

    def test_other_workspace_employee_conflicts(self):
        cursor = FakeCursor(employees=[
            booked(resource_id=43, workspace=42)
        ])
        self.rejected(cursor)

    def test_other_business_does_not_conflict(self):
        cursor = FakeCursor(
            units=[booked(spa=45)],
            employees=[booked(resource_id=43, spa=45)],
        )
        self.check(cursor)

    def test_inactive_reservations_do_not_conflict(self):
        cursor = FakeCursor(
            units=[booked(active=False)],
            employees=[
                booked(resource_id=43, active=False)
            ],
        )
        self.check(cursor)

    def test_overnight_employee_conflict(self):
        overnight_start = START + timedelta(hours=7)
        overnight_end = START + timedelta(hours=13)

        proposal = draft(
            start=overnight_start,
            end=overnight_end,
        )

        cursor = FakeCursor(employees=[
            booked(
                resource_id=43,
                start=START + timedelta(hours=11),
                end=START + timedelta(hours=14),
            )
        ])
        self.rejected(cursor, proposal)

    def test_setup_time_counts_toward_truck_booking(self):
        cursor = FakeCursor(units=[
            booked(
                start=START - timedelta(minutes=30),
                end=START,
            )
        ])

        proposal = draft(
            occupancy_start=START - timedelta(hours=1)
        )

        self.rejected(cursor, proposal)

    def test_naive_timestamps_rejected(self):
        proposal = draft(
            start=START.replace(tzinfo=None)
        )
        self.rejected(FakeCursor(), proposal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
