"""Offline contracts for complete workspace-scoped Event Edit prefill."""

import re
import unittest
from datetime import date, datetime, timezone

from services import event_calendar_edit_read as module


def utc(year, month, day, hour, minute=0):
    return datetime(
        year, month, day, hour, minute,
        tzinfo=timezone.utc,
    )


def fixture():
    event = dict(zip(module._EVENT_COLS, (
        12, 1, "Taco Tuesday", "Keller Park", "100 Main St", None,
        "Keller", "Tarrant", "TX", "76244", "East gate",
        date(2026, 11, 18), date(2026, 11, 19), "America/Chicago",
        "Sam", "555-1234", "sam@example.test", True,
        "confirmed", True, "Fresh tacos!", "Bring water", "Gate 2",
    )))

    day = dict(zip(module._DAY_COLS, (
        100, date(2026, 11, 18),
        utc(2026, 11, 18, 17),
        utc(2026, 11, 18, 20),
        utc(2026, 11, 18, 16),
        utc(2026, 11, 18, 21),
        "Lunch",
    )))

    unit = dict(zip(
        module._UNIT_COLS,
        (100, 501, 72, True),
    ))

    shift = dict(zip(module._SHIFT_COLS, (
        100, 89, 501,
        utc(2026, 11, 18, 17),
        utc(2026, 11, 18, 20),
        "Cook", "Line chef", True,
    )))

    custom = dict(zip(
        module._CUSTOM_COLS,
        (1, "Event Code", "TAC-12"),
    ))

    return {
        "event_calendar_events": [event],
        "event_calendar_daily_schedules": [day],
        "event_calendar_unit_assignments": [unit],
        "event_calendar_employee_assignments": [shift],
        "event_calendar_custom_values": [custom],
    }


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.closed = False
        self.active = None
        self.columns = None

    def execute(self, sql, params):
        match = re.search(r"FROM public\.(\w+)", sql)

        if not match:
            raise AssertionError("Unexpected query")

        self.active = match.group(1)

        self.columns = re.search(
            r"SELECT (.+) FROM public", sql
        ).group(1).split(", ")

        self.calls.append((sql, params))

    def fetchone(self):
        records = self.rows.get(self.active, [])

        return (
            tuple(records[0][key] for key in self.columns)
            if records else None
        )

    def fetchall(self):
        return [
            tuple(item[key] for key in self.columns)
            for item in self.rows.get(self.active, [])
        ]

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur


class EventEditReadTests(unittest.TestCase):
    def setUp(self):
        self.rows = fixture()
        self.conn = FakeConnection(self.rows)

    def load(self, **scope):
        return module.load_event_edit_payload(
            self.conn,
            **({
                "event_id": 12,
                "spa_id": 44,
                "workspace_id": 41,
            } | scope)
        )

    def test_full_prefill_preserves_fields_and_identity(self):
        result = self.load()

        self.assertEqual(
            (result["event_id"], result["event_revision"]),
            (12, 1),
        )
        self.assertEqual(
            result["event"]["venue_name"], "Keller Park"
        )
        self.assertEqual(
            result["event"]["contact_email"],
            "sam@example.test",
        )
        self.assertTrue(
            result["event"]["permits_obtained"]
        )
        self.assertTrue(
            result["event"]["include_on_peachweb"]
        )
        self.assertEqual(
            result["custom_values"]["1"], "TAC-12"
        )
        self.assertEqual(
            result["custom_labels"]["1"], "Event Code"
        )
        self.assertEqual(
            result["days"][0]["equipment_ids"], [72]
        )
        self.assertEqual(
            result["days"][0]["shifts"][0]["employee_id"], 89
        )
        self.assertEqual(
            result["days"][0]["shifts"][0]["equipment_id"], 72
        )
        self.assertEqual(
            result["days"][0]["opens"], "11:00"
        )
        self.assertEqual(
            result["days"][0]["closes"], "14:00"
        )
        self.assertFalse(
            result["days"][1]["operating"]
        )
        self.assertTrue(self.conn.cur.closed)

    def test_every_query_scoped_and_read_only(self):
        self.load()

        self.assertEqual(len(self.conn.cur.calls), 5)

        for sql, params in self.conn.cur.calls:
            self.assertIn(
                "WHERE spa_id = %s "
                "AND business_unit_id = %s "
                "AND event_id = %s",
                sql,
            )
            self.assertEqual(params, (44, 41, 12))
            self.assertTrue(sql.startswith("SELECT "))

    def test_not_found_does_not_load_children(self):
        self.rows["event_calendar_events"] = []

        self.assertIsNone(self.load())
        self.assertEqual(len(self.conn.cur.calls), 1)
        self.assertTrue(self.conn.cur.closed)

    def test_invalid_scope_rejected(self):
        with self.assertRaises(module.EventEditReadError):
            self.load(event_id=True)

        self.assertEqual(len(self.conn.cur.calls), 0)

    def test_overnight_times_and_shift(self):
        day = self.rows[
            "event_calendar_daily_schedules"
        ][0]

        day["opens_at"] = utc(2026, 11, 19, 3)
        day["closes_at"] = utc(2026, 11, 19, 8)

        shift = self.rows[
            "event_calendar_employee_assignments"
        ][0]

        shift["shift_start_at"] = utc(2026, 11, 19, 3)
        shift["shift_end_at"] = utc(2026, 11, 19, 8)

        first = self.load()["days"][0]

        self.assertEqual(
            (first["opens"], first["closes"]),
            ("21:00", "02:00"),
        )
        self.assertTrue(first["closes_next_day"])
        self.assertTrue(
            first["shifts"][0]["ends_next_day"]
        )

    def test_cancelled_event_keeps_inactive_saved_assignments(self):
        self.rows["event_calendar_events"][0][
            "event_status"
        ] = "cancelled"

        self.rows["event_calendar_unit_assignments"][0][
            "is_active"
        ] = False

        self.rows["event_calendar_employee_assignments"][0][
            "is_active"
        ] = False

        result = self.load()

        self.assertEqual(
            result["days"][0]["equipment_ids"], [72]
        )
        self.assertEqual(
            len(result["days"][0]["shifts"]), 1
        )

    def test_non_cancelled_inactive_assignments_not_reintroduced(self):
        self.rows["event_calendar_unit_assignments"][0][
            "is_active"
        ] = False

        self.rows["event_calendar_employee_assignments"][0][
            "is_active"
        ] = False

        result = self.load()

        self.assertEqual(
            result["days"][0]["equipment_ids"], []
        )
        self.assertEqual(
            result["days"][0]["shifts"], []
        )

    def test_unknown_timezone_rejected(self):
        self.rows["event_calendar_events"][0][
            "timezone_name"
        ] = "Unknown/TimeZone"

        with self.assertRaises(module.EventEditReadError):
            self.load()

        self.assertTrue(self.conn.cur.closed)

    def test_orphan_equipment_reference_rejected(self):
        self.rows["event_calendar_employee_assignments"][0][
            "unit_assignment_id"
        ] = 999

        with self.assertRaises(module.EventEditReadError):
            self.load()

        self.assertTrue(self.conn.cur.closed)

    def test_schedule_date_outside_event_rejected(self):
        self.rows["event_calendar_daily_schedules"][0][
            "operating_date"
        ] = date(2026, 11, 20)

        with self.assertRaises(module.EventEditReadError):
            self.load()


if __name__ == "__main__":
    unittest.main()
