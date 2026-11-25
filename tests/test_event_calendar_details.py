"""Event Details service tests; no PostgreSQL writes."""

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from services.event_calendar_details import (
    get_event_details,
)


def utc(hour):
    return datetime(
        2026, 11, 18, hour, 0, tzinfo=timezone.utc
    )


def sample_event():
    return (
        12, "EC-050G Safari Save Test",
        "PeachPOS Test Location",
        "123 main", None,
        "northlake", None, "tx", "76247",
        date(2026, 11, 18),
        date(2026, 11, 18),
        "America/Chicago",
        "scheduled", "Test note", None,
    )


def fixture_results():
    return [
        sample_event(),
        [
            (
                101, date(2026, 11, 18),
                utc(17), utc(20), "",
            )
        ],
        [(101, 201, 2, "Large Truck - CDL", "#00f900")],
        [],
    ]


class FakeCursor:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.current = None
        self.closed = False

    def execute(self, query, params):
        index = len(self.calls)
        self.calls.append((query, params))
        self.current = self.responses[index]

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, responses):
        self.cur = FakeCursor(responses)

    def cursor(self):
        return self.cur


class EventDetailsTests(unittest.TestCase):

    def test_saved_event_details(self):
        conn = FakeConnection(fixture_results())

        result = get_event_details(conn, 12, 44, 41)

        self.assertEqual(result["event_id"], 12)
        self.assertEqual(
            result["name"], "EC-050G Safari Save Test"
        )
        self.assertEqual(
            result["address"]["zip_code"], "76247"
        )
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["notes"], ["Test note"])
        self.assertEqual(len(result["days"]), 1)

        day = result["days"][0]
        self.assertEqual(day["date"], "2026-11-18")
        self.assertEqual(day["opens"], "11:00 AM")
        self.assertEqual(day["closes"], "2:00 PM")
        self.assertEqual(len(day["units"]), 1)
        self.assertEqual(
            day["units"][0]["color"], "#00f900"
        )
        self.assertEqual(
            day["units"][0]["text_color"], "#17212B"
        )
        self.assertEqual(day["employees"], [])
        self.assertTrue(conn.cur.closed)

    def test_all_queries_are_read_only_and_scoped(self):
        conn = FakeConnection(fixture_results())
        get_event_details(conn, 12, 44, 41)

        self.assertEqual(len(conn.cur.calls), 4)

        for query, params in conn.cur.calls:
            with self.subTest(query=query[:30]):
                self.assertTrue(
                    query.lstrip().upper().startswith("SELECT")
                )
                self.assertEqual(params, (12, 44, 41))
                self.assertIn("spa_id = %s", query)
                self.assertIn(
                    "business_unit_id = %s", query
                )
                self.assertIn("event_id = %s", query)

    def test_unknown_event_returns_none(self):
        conn = FakeConnection([None])

        self.assertIsNone(
            get_event_details(conn, 999, 44, 41)
        )
        self.assertEqual(len(conn.cur.calls), 1)
        self.assertTrue(conn.cur.closed)

    def test_invalid_scope_is_rejected(self):
        for ids in (
            (0, 44, 41),
            (12, 0, 41),
            (12, 44, 0),
            (True, 44, 41),
            (12, 44, "41"),
        ):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    get_event_details(
                        FakeConnection([]), *ids
                    )

    def test_invalid_unit_color_is_sanitized(self):
        results = fixture_results()
        results[2] = [
            (101, 201, 2, "Large Truck - CDL", "unsafe")
        ]

        result = get_event_details(
            FakeConnection(results), 12, 44, 41
        )

        self.assertEqual(
            result["days"][0]["units"][0]["color"],
            "#64748B"
        )

    def test_employee_shift_is_grouped_by_day(self):
        results = fixture_results()
        results[3] = [
            (
                101, "Sample Employee",
                utc(18), utc(19),
                "Lead", "Front counter", 201,
            )
        ]

        result = get_event_details(
            FakeConnection(results), 12, 44, 41
        )

        employee = result["days"][0]["employees"][0]

        self.assertEqual(employee["name"], "Sample Employee")
        self.assertEqual(employee["starts"], "12:00 PM")
        self.assertEqual(employee["ends"], "1:00 PM")
        self.assertEqual(employee["role"], "Lead")
        self.assertEqual(employee["unit"], "Large Truck - CDL")

    def test_multiple_operating_days(self):
        results = fixture_results()
        results[1].append(
            (
                102, date(2026, 11, 19),
                utc(17), utc(20), "Second day",
            )
        )

        results[2].append(
            (102, 202, 2, "Large Truck - CDL", "#00f900")
        )

        result = get_event_details(
            FakeConnection(results), 12, 44, 41
        )

        self.assertEqual(len(result["days"]), 2)
        self.assertEqual(
            result["days"][1]["date"], "2026-11-19"
        )
        self.assertEqual(
            result["days"][1]["notes"], "Second day"
        )


if __name__ == "__main__":
    unittest.main()
