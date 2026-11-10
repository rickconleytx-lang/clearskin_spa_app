"""Simulated transaction tests for PeachPOS Event saving.

No real database connections or writes are performed.
These tests verify the service's transaction decisions.
"""

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.event_calendar_save import (
    EventSaveError,
    EventSaveConflict,
    EventSaveInvalid,
    event_request_fingerprint,
    save_event_draft,
)
from services.event_calendar_resources import EventResourceError
from services.event_calendar_availability import EventAvailabilityError


def event_payload():
    return {
        "event": {
            "name": "EC-050 Test Event",
            "venue_name": "Test Food Truck Park",
            "street_address": "123 Test Street",
            "city": "Roanoke",
            "state": "TX",
            "zip_code": "76262",
            "start_date": "2026-11-14",
            "end_date": "2026-11-15",
            "status": "scheduled",
            "include_on_peachweb": False,
            "permits_obtained": False,
        },
        "custom_values": {
            "1": "30 Amp",
            "2": "Booth B12",
            "3": "",
        },
        "days": [
            {
                "date": "2026-11-14",
                "operating": True,
                "opens": "10:00",
                "closes": "18:00",
                "closes_next_day": False,
                "setup": "09:00",
                "breakdown": "19:00",
                "notes": "",
                "equipment_ids": ["1"],
                "shifts": [{
                    "employee_id": "43",
                    "starts": "10:00",
                    "ends": "16:00",
                    "ends_next_day": False,
                    "equipment_id": "1",
                    "role": "Lead",
                    "notes": "",
                }],
            },
            {
                "date": "2026-11-15",
                "operating": True,
                "opens": "11:00",
                "closes": "20:00",
                "closes_next_day": False,
                "setup": "10:00",
                "breakdown": "21:00",
                "notes": "",
                "equipment_ids": ["2"],
                "shifts": [{
                    "employee_id": "43",
                    "starts": "11:00",
                    "ends": "18:00",
                    "ends_next_day": False,
                    "equipment_id": "2",
                    "role": "Lead",
                    "notes": "",
                }],
            },
        ],
    }


class SimulatedExclusionError(Exception):
    pgcode = "23P01"


class FakeConnection:
    """Records SQL and simulates returned database identities."""

    def __init__(self):
        self.autocommit = False
        self.timezone_name = "America/Chicago"
        self.prior_submission = None
        self.fail_insert_table = None
        self.fail_completion = False
        self.fail_custom_value = False
        self.commits = 0
        self.rollbacks = 0
        self.queries = []
        self.inserts = []
        self.daily_next = 700
        self.unit_next = 800

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.one = None
        self.many = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        c = self.connection
        statement = " ".join(sql.lower().split())

        c.queries.append((statement, params))
        self.one = None
        self.many = []

        if statement.startswith(
            "insert into event_calendar_save_submissions"
        ):
            if c.prior_submission is None:
                self.one = (params[0],)

        elif (
            statement.startswith("select spa_id,")
            and "from event_calendar_save_submissions"
                in statement
        ):
            self.one = c.prior_submission

        elif statement.startswith(
            "select timezone_name from spas"
        ):
            if c.timezone_name:
                self.one = (c.timezone_name,)

        elif statement.startswith(
            "insert into event_calendar_events"
        ):
            c.inserts.append(("event", params))
            self.one = (501,)

        elif statement.startswith(
            "insert into event_calendar_daily_schedules"
        ):
            c.inserts.append(("daily", params))
            c.daily_next += 1
            self.one = (c.daily_next,)

        elif statement.startswith(
            "insert into event_calendar_unit_assignments"
        ):
            if c.fail_insert_table == "unit":
                raise SimulatedExclusionError()

            c.inserts.append(("unit", params))
            c.unit_next += 1
            self.one = (c.unit_next,)

        elif statement.startswith(
            "insert into event_calendar_employee_assignments"
        ):
            if c.fail_insert_table == "employee":
                raise SimulatedExclusionError()

            c.inserts.append(("employee", params))

        elif statement.startswith(
            "select slot_number, field_label"
        ):
            self.many = [
                (1, "Electrical Hookup"),
                (2, "Vendor Booth Number"),
                (3, "Event Fee"),
            ]

        elif statement.startswith(
            "insert into event_calendar_custom_values"
        ):
            if c.fail_custom_value:
                raise RuntimeError("Simulated custom value failure")

            c.inserts.append(("custom", params))

        elif statement.startswith(
            "update event_calendar_save_submissions"
        ):
            if not c.fail_completion:
                self.one = (501,)

        else:
            raise AssertionError(
                "Unexpected SQL: " + statement[:130]
            )

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class EventSaveTests(unittest.TestCase):

    def setUp(self):
        self.conn = FakeConnection()
        self.payload = event_payload()
        self.token = str(uuid.uuid4())

        owner_patch = mock.patch(
            "services.event_calendar_save."
            "validate_event_resource_ownership",
            return_value={"ownership_validated": True},
        )

        availability_patch = mock.patch(
            "services.event_calendar_save."
            "validate_existing_event_availability",
            return_value={"availability_validated": True},
        )

        self.owner = owner_patch.start()
        self.availability = availability_patch.start()

        self.addCleanup(owner_patch.stop)
        self.addCleanup(availability_patch.stop)

    def save(self):
        return save_event_draft(
            self.conn,
            self.payload,
            44,
            41,
            34,
            self.token,
        )

    def test_complete_two_day_event(self):
        result = self.save()

        self.assertTrue(result["created"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(result["event_id"], 501)

        self.assertEqual(result["operating_days"], 2)
        self.assertEqual(result["equipment_assignments"], 2)
        self.assertEqual(result["employee_shifts"], 2)
        self.assertEqual(result["custom_values"], 2)

        kinds = [kind for kind, _ in self.conn.inserts]

        self.assertEqual(kinds.count("event"), 1)
        self.assertEqual(kinds.count("daily"), 2)
        self.assertEqual(kinds.count("unit"), 2)
        self.assertEqual(kinds.count("employee"), 2)
        self.assertEqual(kinds.count("custom"), 2)

        self.assertEqual(self.conn.commits, 1)
        self.assertEqual(self.conn.rollbacks, 0)

        employees = [
            params for kind, params in self.conn.inserts
            if kind == "employee"
        ]

        self.assertEqual(
            [item[5] for item in employees],
            [801, 802],
        )

        custom = [
            params for kind, params in self.conn.inserts
            if kind == "custom"
        ]

        self.assertEqual(custom[0][-2:], (
            "Electrical Hookup", "30 Amp"
        ))
        self.assertEqual(custom[1][-2:], (
            "Vendor Booth Number", "Booth B12"
        ))

        self.owner.assert_called_once()
        self.availability.assert_called_once()

        self.assertEqual(
            self.owner.call_args.args[2:],
            (44, 41),
        )
        self.assertEqual(
            self.availability.call_args.args[2],
            44,
        )

    def test_exact_retry_returns_original_event(self):
        self.conn.prior_submission = (
            44,
            41,
            event_request_fingerprint(self.payload),
            777,
            datetime.now(timezone.utc),
        )

        result = self.save()

        self.assertEqual(result["event_id"], 777)
        self.assertFalse(result["created"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertEqual(self.conn.inserts, [])
        self.owner.assert_not_called()

    def test_changed_payload_with_same_token_rejected(self):
        different = event_payload()
        different["event"]["name"] = "Different event"

        self.conn.prior_submission = (
            44,
            41,
            event_request_fingerprint(different),
            777,
            datetime.now(timezone.utc),
        )

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_cross_workspace_token_rejected(self):
        self.conn.prior_submission = (
            44,
            42,
            event_request_fingerprint(self.payload),
            777,
            datetime.now(timezone.utc),
        )

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_incomplete_prior_submission_rejected(self):
        self.conn.prior_submission = (
            44,
            41,
            event_request_fingerprint(self.payload),
            None,
            None,
        )

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_missing_timezone_rolls_back(self):
        self.conn.timezone_name = None

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertEqual(self.conn.inserts, [])

    def test_invalid_event_data_rolls_back(self):
        self.payload["days"] = []

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_resource_eligibility_failure_rolls_back(self):
        self.owner.side_effect = EventResourceError(
            "Selected resource is inactive."
        )

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.availability.assert_not_called()
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertEqual(self.conn.inserts, [])

    def test_existing_booking_conflict_rolls_back(self):
        self.availability.side_effect = EventAvailabilityError(
            "Equipment is already booked."
        )

        with self.assertRaises(EventSaveConflict):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertEqual(self.conn.inserts, [])

    def test_postgresql_unit_overlap_rolls_back(self):
        self.conn.fail_insert_table = "unit"

        with self.assertRaises(EventSaveConflict):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_postgresql_employee_overlap_rolls_back(self):
        self.conn.fail_insert_table = "employee"

        with self.assertRaises(EventSaveConflict):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_custom_field_failure_rolls_back(self):
        self.conn.fail_custom_value = True

        with self.assertRaises(RuntimeError):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_submission_completion_failure_rolls_back(self):
        self.conn.fail_completion = True

        with self.assertRaises(EventSaveError):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_cancelled_event_has_inactive_reservations(self):
        self.payload["event"]["status"] = "cancelled"

        result = self.save()

        self.assertTrue(result["created"])
        self.availability.assert_not_called()

        for kind, params in self.conn.inserts:
            if kind in ("unit", "employee"):
                self.assertIs(params[-2], False)

        self.assertEqual(self.conn.commits, 1)

    def test_autocommit_connection_rejected(self):
        self.conn.autocommit = True

        with self.assertRaises(EventSaveError):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.inserts, [])

    def test_invalid_submission_token_rejected(self):
        self.token = "not-a-uuid"

        with self.assertRaises(EventSaveInvalid):
            self.save()

        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.inserts, [])

    def test_fingerprint_is_stable_and_detects_changes(self):
        original = event_request_fingerprint(self.payload)

        reordered = {
            "days": self.payload["days"],
            "custom_values": self.payload["custom_values"],
            "event": self.payload["event"],
        }

        self.assertEqual(
            original,
            event_request_fingerprint(reordered),
        )

        reordered["event"] = dict(reordered["event"])
        reordered["event"]["name"] = "Changed"

        self.assertNotEqual(
            original,
            event_request_fingerprint(reordered),
        )


if __name__ == "__main__":
    unittest.main()
