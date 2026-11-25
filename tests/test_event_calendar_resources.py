import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from services.event_calendar_resources import (
    EventResourceError,
    validate_event_resource_ownership,
)


class FakeCursor:
    def __init__(self, units=(), employees=()):
        # Entries represent active resources in a workspace.
        self.units = set(units)
        self.employees = set(employees)
        self.rows = []
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        spa_id, workspace_id, selected = params

        if "FROM event_units" in sql:
            assert "is_active = TRUE" in sql
            assert "business_unit_id = %s" in sql
            assert "spa_id = %s" in sql

            self.rows = [
                (item,)
                for item in selected
                if (spa_id, workspace_id, item) in self.units
            ]

        elif "FROM employee_business_unit_memberships" in sql:
            assert "JOIN employees AS e" in sql
            assert "m.is_active = TRUE" in sql
            assert "e.is_active = TRUE" in sql
            assert "m.business_unit_id = %s" in sql
            assert "m.spa_id = %s" in sql

            self.rows = [
                (item,)
                for item in selected
                if (spa_id, workspace_id, item) in self.employees
            ]

        else:
            raise AssertionError("Unexpected SQL query.")

    def fetchall(self):
        return self.rows


def draft(units=None, employee_ids=None):
    return {
        "days": [{
            "operating": True,
            "equipment_ids": units if units is not None else [],
            "shifts": [
                {"employee_id": employee_id, "unit_id": None}
                for employee_id in (
                    employee_ids if employee_ids is not None else []
                )
            ],
        }]
    }


class EventResourceTests(unittest.TestCase):
    def check(self, cursor, normalized, spa=44, workspace=41):
        return validate_event_resource_ownership(
            cursor, normalized, spa, workspace
        )

    def rejected(self, cursor, normalized, spa=44, workspace=41):
        with self.assertRaises(EventResourceError):
            self.check(cursor, normalized, spa, workspace)

    def test_active_resources_accepted(self):
        cursor = FakeCursor(
            units={(44, 41, 1), (44, 41, 2)},
            employees={(44, 41, 43)},
        )
        result = self.check(cursor, draft([1, 2], [43]))
        self.assertEqual(result["event_unit_ids"], [1, 2])
        self.assertEqual(result["employee_ids"], [43])
        self.assertEqual(len(cursor.calls), 2)

    def test_unknown_equipment_rejected(self):
        self.rejected(
            FakeCursor(units={(44, 41, 1)}),
            draft([1, 999]),
        )

    def test_other_workspace_equipment_rejected(self):
        self.rejected(
            FakeCursor(units={(44, 42, 1)}),
            draft([1]),
        )

    def test_inactive_equipment_rejected(self):
        self.rejected(FakeCursor(), draft([1]))

    def test_inactive_employee_rejected(self):
        self.rejected(
            FakeCursor(),
            draft(employee_ids=[43]),
        )

    def test_other_workspace_employee_rejected(self):
        self.rejected(
            FakeCursor(employees={(44, 42, 43)}),
            draft(employee_ids=[43]),
        )

    def test_no_assignments_requires_no_queries(self):
        cursor = FakeCursor()
        result = self.check(cursor, draft())
        self.assertEqual(cursor.calls, [])
        self.assertTrue(result["ownership_validated"])

    def test_unassigned_shift_still_requires_employee(self):
        self.rejected(
            FakeCursor(),
            draft(employee_ids=[43]),
        )

    def test_malformed_identifier_rejected(self):
        self.rejected(FakeCursor(), draft(units=["1"]))

    def test_invalid_workspace_scope_rejected(self):
        self.rejected(
            FakeCursor(),
            draft(),
            workspace=True,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
