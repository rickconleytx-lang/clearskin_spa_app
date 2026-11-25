"""EC-064-2A: pure Year View model, no Flask or database access."""
import unittest
from datetime import date, datetime
from services.event_calendar_year import EventYearViewError, build_year_view


def entry(day, events=1, units=1, cancelled=0):
    return {'date': day, 'events': events, 'units': units,
            'cancelled': cancelled}


def cell(view, month, target):
    return next(
        c for week in view['months'][month-1]['weeks'] for c in week
        if c['date'] == target
    )


class YearModelTests(unittest.TestCase):
    def test_twelve_sunday_first_months(self):
        view = build_year_view([], 2026, date(2026, 11, 11))
        self.assertEqual(len(view['months']), 12)
        self.assertEqual(view['months'][0]['name'], 'January')
        self.assertEqual(view['months'][11]['name'], 'December')
        for month in view['months']:
            for week in month['weeks']:
                self.assertEqual(len(week), 7)
                self.assertEqual(week[0]['date'].weekday(), 6)

    def test_operating_day_shown_in_correct_month(self):
        view = build_year_view([entry(date(2026, 12, 5), 1, 3)], 2026)
        day = cell(view, 12, date(2026, 12, 5))
        self.assertEqual((day['events'], day['units']), (1, 3))
        self.assertTrue(day['has_activity'])
        self.assertEqual(view['months'][11]['active_dates'], 1)

    def test_year_counts_event_days_not_distinct_event_ids(self):
        view = build_year_view([
            entry(date(2026, 12, 5), 1, 3),
            entry(date(2026, 12, 6), 1, 3),
        ], 2026)
        self.assertEqual(view['event_days'], 2)
        self.assertEqual(view['unit_days'], 6)
        self.assertEqual(view['active_dates'], 2)

    def test_multiple_events_one_day(self):
        view = build_year_view([entry(date(2026, 6, 15), 2, 3)], 2026)
        self.assertEqual(view['months'][5]['event_days'], 2)
        self.assertEqual(view['months'][5]['active_dates'], 1)

    def test_cancelled_only_is_not_active(self):
        view = build_year_view([entry(date(2026, 6, 15), 0, 0, 1)], 2026)
        self.assertEqual(view['active_dates'], 0)
        self.assertEqual(view['cancelled_event_days'], 1)
        self.assertFalse(cell(view, 6, date(2026, 6, 15))['has_activity'])

    def test_leap_day_supported(self):
        view = build_year_view([entry(date(2028, 2, 29))], 2028)
        self.assertEqual(cell(view, 2, date(2028, 2, 29))['events'], 1)

    def test_neighbour_month_cells_do_not_duplicate_totals(self):
        view = build_year_view([entry(date(2026, 3, 31))], 2026)
        self.assertEqual(view['event_days'], 1)
        self.assertEqual(cell(view, 4, date(2026, 3, 31))['events'], 0)
        self.assertFalse(cell(view, 4, date(2026, 3, 31))['in_month'])

    def test_current_day_highlight(self):
        today = date(2026, 11, 11)
        view = build_year_view([], 2026, today)
        self.assertTrue(cell(view, 11, today)['today'])
        self.assertEqual(cell(view, 11, today)['iso'], '2026-11-11')

    def test_empty_year_zero_totals(self):
        view = build_year_view([], 2026)
        self.assertEqual((view['active_dates'], view['event_days'],
                          view['unit_days']), (0, 0, 0))

    def test_year_navigation_bounds(self):
        self.assertIsNone(build_year_view([], 2000)['previous_year'])
        self.assertIsNone(build_year_view([], 2100)['next_year'])
        self.assertEqual(build_year_view([], 2026)['next_year'], 2027)

    def test_invalid_year_rejected(self):
        for value in (1999, 2101, True, 2026.0):
            with self.subTest(value=value), self.assertRaises(EventYearViewError):
                build_year_view([], value)

    def test_invalid_summary_rejected(self):
        for values in (
            [entry(date(2025, 12, 31))],
            [entry(date(2026, 12, 1), -1)],
            [entry(date(2026, 12, 1), 1, '3')],
            [entry(date(2026, 12, 1))] * 2,
            [entry(datetime(2026, 12, 1))],
            ['junk'],
        ):
            with self.subTest(values=values), self.assertRaises(EventYearViewError):
                build_year_view(values, 2026)


if __name__ == '__main__':
    unittest.main()
