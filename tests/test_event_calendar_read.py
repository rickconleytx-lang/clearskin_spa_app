"""Read-only event retrieval and workspace-isolation tests."""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from services.event_calendar_read import (
    EventCalendarReadError,
    list_event_calendar_rows,
    safe_calendar_color,
)


START = date(2026, 11, 1)
END = date(2026, 12, 5)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None
        self.closed = False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur


def sample_row(color="#00f900"):
    return (
        12,
        "EC-050G Safari Save Test",
        date(2026, 11, 18),
        date(2026, 11, 18),
        "scheduled",
        "PeachPOS Test Location",
        "Northlake",
        "TX",
        "America/Chicago",
        10,
        date(2026, 11, 18),
        None,
        None,
        2,
        "Large Truck - CDL",
        color,
    )


class EventCalendarReadTests(unittest.TestCase):

    def test_saved_event_and_unit_color(self):
        conn = FakeConnection([sample_row()])

        rows = list_event_calendar_rows(
            conn, 44, 41, START, END
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], 12)
        self.assertEqual(rows[0]["event_unit_id"], 2)
        self.assertEqual(
            rows[0]["calendar_color"], "#00f900"
        )
        self.assertTrue(conn.cur.closed)

    def test_query_is_read_only_and_workspace_scoped(self):
        conn = FakeConnection([])

        list_event_calendar_rows(
            conn, 44, 41, START, END
        )

        query = conn.cur.query

        self.assertTrue(
            query.lstrip().upper().startswith("SELECT")
        )

        self.assertIn("WHERE e.spa_id = %s", query)
        self.assertIn("e.business_unit_id = %s", query)
        self.assertIn("d.spa_id = e.spa_id", query)
        self.assertIn(
            "d.business_unit_id = e.business_unit_id",
            query
        )
        self.assertIn("u.spa_id = e.spa_id", query)
        self.assertIn(
            "u.business_unit_id = e.business_unit_id",
            query
        )

        self.assertEqual(
            conn.cur.params,
            (START, END, 44, 41, END, START),
        )

    def test_empty_calendar(self):
        conn = FakeConnection([])

        self.assertEqual(
            list_event_calendar_rows(
                conn, 44, 41, START, END
            ),
            []
        )

    def test_invalid_color_uses_safe_fallback(self):
        self.assertEqual(
            safe_calendar_color("not-a-color"),
            "#64748B"
        )

        conn = FakeConnection([
            sample_row("invalid-color")
        ])

        rows = list_event_calendar_rows(
            conn, 44, 41, START, END
        )

        self.assertEqual(
            rows[0]["calendar_color"], "#64748B"
        )

    def test_invalid_business_scope_rejected(self):
        for spa_id, workspace_id in (
            (0, 41),
            (44, 0),
            (True, 41),
            (44, "41"),
        ):
            with self.subTest(
                spa_id=spa_id,
                workspace_id=workspace_id
            ):
                with self.assertRaises(
                    EventCalendarReadError
                ):
                    list_event_calendar_rows(
                        FakeConnection([]),
                        spa_id,
                        workspace_id,
                        START,
                        END,
                    )

    def test_invalid_date_range_rejected(self):
        for start, end in (
            (END, START),
            (START, date(2027, 1, 1)),
            ("2026-11-01", END),
        ):
            with self.subTest(start=start, end=end):
                with self.assertRaises(
                    EventCalendarReadError
                ):
                    list_event_calendar_rows(
                        FakeConnection([]),
                        44, 41, start, end
                    )


if __name__ == "__main__":
    unittest.main()
