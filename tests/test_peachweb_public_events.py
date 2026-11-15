import unittest

from datetime import date, datetime, timezone

from services.peachweb_public_events import (
    PUBLIC_EVENT_COLUMNS,
    PUBLIC_EVENT_DAY_SQL,
    fetch_public_event_days,
)


class FakeCursor:

    def __init__(self, rows=()):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class PublicEventTests(unittest.TestCase):

    def setUp(self):
        self.start = date(2026, 11, 16)
        self.end = date(2026, 12, 20)

    def fetch(self, cursor):
        return fetch_public_event_days(
            cursor,
            spa_id=44,
            business_unit_id=41,
            window_start=self.start,
            window_end=self.end,
        )

    def test_workspace_scoping_parameters(self):
        cur = FakeCursor()
        self.fetch(cur)

        self.assertEqual(
            cur.params,
            (44, 41, self.start, self.end),
        )

    def test_publication_archive_and_tier_guards(self):
        sql = PUBLIC_EVENT_DAY_SQL.lower()

        self.assertIn("e.is_public is true", sql)
        self.assertIn("m.archived_at is not null", sql)
        self.assertIn("not exists", sql)
        self.assertIn("e.event_status <> 'cancelled'", sql)
        self.assertIn("lower(st.tier_code) = 'pos'", sql)
        self.assertIn("e.spa_id = %s", sql)
        self.assertIn("e.business_unit_id = %s", sql)
        self.assertIn("s.active = true", sql)
        self.assertIn("bu.is_active = true", sql)

    def test_no_private_fields_in_public_projection(self):
        projection = PUBLIC_EVENT_DAY_SQL.split(
            "FROM event_calendar_events", 1
        )[0].lower()

        for private in (
            "contact_name",
            "contact_phone",
            "contact_email",
            "notes_1",
            "notes_2",
            "parking_setup_location",
            "permits_obtained",
            "daily_notes",
            "setup_at",
            "breakdown_at",
            "employee",
        ):
            self.assertNotIn(private, projection)

    def test_approved_result_fields_only(self):
        row = (
            3,
            "Hilltop Truck Park",
            "Hilltop Truck Park",
            "Northlake",
            "TX",
            "100 Example Street",
            None,
            "76247",
            "America/Chicago",
            date(2026, 11, 16),
            datetime(2026, 11, 16, 16, tzinfo=timezone.utc),
            datetime(2026, 11, 17, 3, tzinfo=timezone.utc),
        )

        result = self.fetch(FakeCursor([row]))

        self.assertEqual(len(result), 1)
        self.assertEqual(
            tuple(result[0]),
            PUBLIC_EVENT_COLUMNS,
        )
        self.assertEqual(
            result[0]["city"],
            "Northlake",
        )
        self.assertEqual(
            result[0]["event_id"],
            3,
        )

    def test_invalid_business_identity_rejected(self):
        cur = FakeCursor()

        with self.assertRaises(ValueError):
            fetch_public_event_days(
                cur,
                spa_id=0,
                business_unit_id=41,
                window_start=self.start,
                window_end=self.end,
            )

        self.assertIsNone(cur.sql)

    def test_invalid_window_rejected(self):
        cur = FakeCursor()

        with self.assertRaises(ValueError):
            fetch_public_event_days(
                cur,
                spa_id=44,
                business_unit_id=41,
                window_start=self.start,
                window_end=date(2026, 12, 21),
            )

        self.assertIsNone(cur.sql)

    def test_query_is_read_only(self):
        sql = PUBLIC_EVENT_DAY_SQL.upper()

        for keyword in (
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "DROP TABLE",
            "ALTER TABLE",
        ):
            self.assertNotIn(keyword, sql)


if __name__ == "__main__":
    unittest.main()
