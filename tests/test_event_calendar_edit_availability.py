"""Editing availability: exclude only the original event.

Offline tests preserve the existing Add Event availability behavior.
"""

import unittest
from datetime import datetime, timedelta, timezone

from services.event_calendar_availability import (
    EventAvailabilityError,
    validate_existing_event_availability,
)


START = datetime(2026, 11, 18, 17, tzinfo=timezone.utc)
END = START + timedelta(hours=3)


def proposal(unit=72, employee=89):
    return {
        "days": [{
            "operating": True,
            "equipment_ids": (
                [] if unit is None else [unit]
            ),
            "occupancy_start": START,
            "occupancy_end": END,
            "shifts": (
                [] if employee is None else [{
                    "employee_id": employee,
                    "starts_at": START,
                    "ends_at": END,
                }]
            ),
        }]
    }


def booking(
    resource, *, event_id=12, workspace=41,
    spa=44, start=START, end=END, active=True
):
    return (
        spa, workspace, event_id,
        resource, start, end, active,
    )


class FakeCursor:

    def __init__(self, units=(), employees=()):
        self.units = list(units)
        self.employees = list(employees)
        self.calls = []
        self.rows = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

        assert "WHERE spa_id = %s" in sql
        assert "is_active = TRUE" in sql

        if "FROM event_calendar_unit_assignments" in sql:
            records = self.units
        elif "FROM event_calendar_employee_assignments" in sql:
            records = self.employees
        else:
            raise AssertionError("Unexpected SQL table.")

        if len(params) == 4:
            spa, ids, latest, earliest = params
            excluded = None

            assert "AND NOT (" not in sql

        elif len(params) == 6:
            spa, ids, latest, earliest, workspace, event = params
            excluded = (workspace, event)

            assert "AND NOT (" in sql
            assert "business_unit_id = %s" in sql
            assert "event_id = %s" in sql

        else:
            raise AssertionError("Unexpected query parameters.")

        self.rows = []

        for (
            found_spa, found_workspace, found_event,
            resource, start, end, active
        ) in records:
            if found_spa != spa:
                continue

            if resource not in ids or not active:
                continue

            if not (start < latest and end > earliest):
                continue

            if excluded == (found_workspace, found_event):
                continue

            self.rows.append((resource, start, end))

    def fetchall(self):
        return self.rows


class EventEditAvailabilityTests(unittest.TestCase):

    def check(self, cursor, *, excluded=(41, 12),
              draft=None, spa=44):
        return validate_existing_event_availability(
            cursor,
            proposal() if draft is None else draft,
            spa,
            excluded_event=excluded,
        )

    def test_create_mode_still_rejects_existing_booking(self):
        cursor = FakeCursor(units=[booking(72)])

        with self.assertRaises(EventAvailabilityError):
            self.check(cursor, excluded=None)

        self.assertEqual(len(cursor.calls[0][1]), 4)

    def test_edit_ignores_own_equipment_and_shift(self):
        cursor = FakeCursor(
            units=[booking(72)],
            employees=[booking(89)],
        )

        result = self.check(cursor)

        self.assertTrue(result["availability_validated"])
        self.assertEqual(
            result["existing_unit_reservations_examined"], 0
        )
        self.assertEqual(
            result["existing_employee_shifts_examined"], 0
        )

        self.assertEqual(len(cursor.calls), 2)

        for sql, params in cursor.calls:
            self.assertEqual(params[-2:], (41, 12))
            self.assertIn("business_unit_id = %s", sql)
            self.assertIn("event_id = %s", sql)

    def test_other_event_same_workspace_truck_rejected(self):
        cursor = FakeCursor(
            units=[booking(72, event_id=14)]
        )

        with self.assertRaises(EventAvailabilityError):
            self.check(cursor)

    def test_other_workspace_truck_conflict_preserved(self):
        cursor = FakeCursor(
            units=[
                booking(
                    72, event_id=18, workspace=42
                )
            ]
        )

        with self.assertRaises(EventAvailabilityError):
            self.check(cursor)

    def test_other_event_employee_conflict_preserved(self):
        cursor = FakeCursor(
            employees=[
                booking(89, event_id=14)
            ]
        )

        with self.assertRaises(EventAvailabilityError):
            self.check(cursor)

    def test_other_workspace_employee_conflict_preserved(self):
        cursor = FakeCursor(
            employees=[
                booking(
                    89, event_id=18, workspace=42
                )
            ]
        )

        with self.assertRaises(EventAvailabilityError):
            self.check(cursor)

    def test_other_business_does_not_conflict(self):
        cursor = FakeCursor(
            units=[booking(72, spa=45)],
            employees=[booking(89, spa=45)],
        )

        self.check(cursor)

    def test_adjacent_reservation_allowed(self):
        cursor = FakeCursor(
            units=[
                booking(
                    72,
                    event_id=14,
                    start=END,
                    end=END + timedelta(hours=2),
                )
            ]
        )

        self.check(cursor)

    def test_invalid_exclusions_rejected_before_sql(self):
        invalid = (
            (True, 12),
            (41, 0),
            (41, "12"),
            (41,),
            [41, 12],
            "41:12",
        )

        for value in invalid:
            with self.subTest(value=value):
                cursor = FakeCursor()

                with self.assertRaises(
                    EventAvailabilityError
                ):
                    self.check(cursor, excluded=value)

                self.assertEqual(cursor.calls, [])

    def test_no_resources_avoids_queries(self):
        cursor = FakeCursor()

        result = self.check(
            cursor,
            draft=proposal(
                unit=None, employee=None
            ),
        )

        self.assertTrue(result["availability_validated"])
        self.assertEqual(cursor.calls, [])


if __name__ == "__main__":
    unittest.main()
