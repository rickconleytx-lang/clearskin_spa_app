"""EC-064-2A: no-DB tests for safe year-only aggregate retrieval."""
import unittest
from datetime import date, datetime
from services.event_calendar_year_read import (
    EventYearReadError, list_year_day_summaries,
)


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None
        self.closed = False

    def execute(self, query, params):
        self.query, self.params = query, params

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, rows):
        self.cur = Cursor(rows)

    def cursor(self):
        return self.cur


class YearReadTests(unittest.TestCase):
    def test_year_read_one_query_and_summary(self):
        conn = Connection([(date(2026, 12, 5), 1, 3, 0)])
        actual = list_year_day_summaries(conn, 44, 41, 2026)
        self.assertEqual(actual, [{
            'date': date(2026, 12, 5), 'events': 1,
            'units': 3, 'cancelled': 0,
        }])
        self.assertTrue(conn.cur.closed)

    def test_read_is_scoped_and_bounded_to_one_year(self):
        conn = Connection([])
        list_year_day_summaries(conn, 44, 41, 2026)
        sql = conn.cur.query
        self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
        for fragment in (
            'WHERE d.spa_id = %s', 'd.business_unit_id = %s',
            'e.spa_id = d.spa_id',
            'e.business_unit_id = d.business_unit_id',
            'a.spa_id = d.spa_id',
            'a.business_unit_id = d.business_unit_id',
            'a.daily_schedule_id = d.daily_schedule_id',
            'a.is_active = TRUE', 'd.operating_date >= %s',
            'd.operating_date < %s',
            'GROUP BY d.operating_date',
        ):
            self.assertIn(fragment, sql)
        self.assertEqual(conn.cur.params, (
            44, 41, date(2026, 1, 1), date(2027, 1, 1)
        ))

    def test_aggregate_counts_distinct_events_and_units(self):
        conn = Connection([])
        list_year_day_summaries(conn, 44, 41, 2026)
        self.assertIn('COUNT(DISTINCT d.event_id)', conn.cur.query)
        self.assertIn('COUNT(DISTINCT a.event_unit_id)', conn.cur.query)
        self.assertIn("event_status <> 'cancelled'", conn.cur.query)
        self.assertIn("event_status = 'cancelled'", conn.cur.query)

    def test_no_write_or_private_details_read(self):
        conn = Connection([])
        list_year_day_summaries(conn, 44, 41, 2026)
        sql = conn.cur.query.lower()
        for forbidden in (
            'insert ', 'update ', 'delete ', 'contact_',
            'notes_1', 'notes_2', 'employee_',
        ):
            self.assertNotIn(forbidden, sql)

    def test_empty_year(self):
        self.assertEqual(
            list_year_day_summaries(Connection([]), 44, 41, 2026), []
        )

    def test_invalid_scope_rejected_before_query(self):
        for scope in ((0, 41, 2026), (44, 0, 2026),
                      (True, 41, 2026), (44, '41', 2026)):
            with self.subTest(scope=scope), self.assertRaises(EventYearReadError):
                list_year_day_summaries(Connection([]), *scope)

    def test_invalid_year_rejected(self):
        for year in (1999, 2101, True, 2026.0, '2026'):
            with self.subTest(year=year), self.assertRaises(EventYearReadError):
                list_year_day_summaries(Connection([]), 44, 41, year)

    def test_rejects_invalid_rows(self):
        invalid = [
            [(date(2025, 12, 31), 1, 1, 0)],
            [(datetime(2026, 1, 1), 1, 1, 0)],
            [(date(2026, 12, 1), -1, 0, 0)],
            [(date(2026, 12, 1), 1, True, 0)],
            [(date(2026, 12, 1), 1, 1)],
        ]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(EventYearReadError):
                list_year_day_summaries(Connection(rows), 44, 41, 2026)

    def test_duplicate_date_rejected(self):
        rows = [(date(2026, 12, 5), 1, 1, 0)] * 2
        with self.assertRaises(EventYearReadError):
            list_year_day_summaries(Connection(rows), 44, 41, 2026)

    def test_year_limit_2100(self):
        conn = Connection([])
        list_year_day_summaries(conn, 44, 41, 2100)
        self.assertEqual(conn.cur.params[-1], date(2101, 1, 1))


if __name__ == '__main__':
    unittest.main()
