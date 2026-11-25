"""EC-064-3A: pure, database-free weekly calendar model tests."""
import unittest
from datetime import date, datetime, timezone
from services.event_calendar_week import (
    EventWeekViewError,
    build_week_view,
    week_bounds,
)


def sample(operating_date=date(2026, 12, 5), event_id=21,
           unit_id=1, opens=16, closes=23, **changes):
    row = {
        "event_id": event_id,
        "event_name": "Food Truck Festival",
        "venue_name": "Downtown Square",
        "city": "Southlake",
        "state": "TX",
        "event_status": "scheduled",
        "timezone_name": "America/Chicago",
        "daily_schedule_id": 120,
        "operating_date": operating_date,
        "opens_at": datetime(2026, 12, 5, opens, tzinfo=timezone.utc),
        "closes_at": datetime(2026, 12, 5, closes, tzinfo=timezone.utc),
        "event_unit_id": unit_id,
        "unit_name": f"Truck {unit_id}",
        "calendar_color": "#00f900",
    }
    row.update(changes)
    return row


class WeekBoundsTests(unittest.TestCase):
    def test_midweek_anchor_resolves_to_sunday(self):
        self.assertEqual(week_bounds(date(2026, 12, 2)),
                         (date(2026, 11, 29), date(2026, 12, 5)))

    def test_sunday_anchor_is_week_start(self):
        self.assertEqual(week_bounds(date(2026, 12, 6))[0],
                         date(2026, 12, 6))

    def test_saturday_anchor_is_week_end(self):
        self.assertEqual(week_bounds(date(2026, 12, 5))[1],
                         date(2026, 12, 5))

    def test_leap_day_in_week(self):
        self.assertEqual(week_bounds(date(2028, 2, 29)),
                         (date(2028, 2, 27), date(2028, 3, 4)))

    def test_reject_non_dates_and_datetime(self):
        for val in (None, "2026-12-05", 123, True,
                    datetime(2026, 12, 5)):
            with self.subTest(value=val), self.assertRaises(EventWeekViewError):
                week_bounds(val)

    def test_reject_out_of_range_year(self):
        for val in (date(1999, 12, 31), date(2101, 1, 1)):
            with self.subTest(value=val), self.assertRaises(EventWeekViewError):
                week_bounds(val)


class WeekPresentationTests(unittest.TestCase):
    def test_empty_week_has_seven_days(self):
        view = build_week_view([], date(2026, 12, 6), date(2026, 12, 8))
        self.assertEqual(len(view["days"]), 7)
        self.assertEqual(view["entry_count"], 0)
        self.assertEqual(view["event_day_count"], 0)
        self.assertEqual(view["days"][0]["weekday"], "Sun")
        self.assertEqual(view["days"][-1]["weekday"], "Sat")

    def test_business_timezone_hours(self):
        view = build_week_view([sample()], date(2026, 12, 5))
        item = view["days"][-1]["entries"][0]
        self.assertEqual(item["hours"], "10:00 AM – 5:00 PM")
        self.assertEqual(item["unit"], "Truck 1")

    def test_three_trucks_on_one_event_day(self):
        rows = [sample(unit_id=i) for i in (1, 2, 3)]
        view = build_week_view(rows, date(2026, 12, 5))
        day = view["days"][-1]
        self.assertEqual(day["assignment_count"], 3)
        self.assertEqual(day["event_count"], 1)
        self.assertEqual(view["event_day_count"], 1)

    def test_duplicate_join_records_not_double_counted(self):
        row = sample()
        view = build_week_view([row, dict(row)], date(2026, 12, 5))
        self.assertEqual(view["entry_count"], 1)

    def test_same_truck_two_different_events(self):
        rows = [sample(event_id=21), sample(event_id=22)]
        view = build_week_view(rows, date(2026, 12, 5))
        self.assertEqual(view["entry_count"], 2)
        self.assertEqual(view["event_day_count"], 2)

    def test_multi_day_event_shows_on_each_operating_date(self):
        rows = [sample(operating_date=date(2026, 12, d))
                for d in (4, 5, 6)]
        view = build_week_view(rows, date(2026, 12, 5))
        self.assertEqual(view["entry_count"], 2)  # week ends on Saturday
        self.assertEqual(view["days"][5]["assignment_count"], 1)
        self.assertEqual(view["days"][6]["assignment_count"], 1)

    def test_date_outside_window_is_skipped(self):
        view = build_week_view([sample(operating_date=date(2026, 12, 6))],
                               date(2026, 12, 5))
        self.assertEqual(view["entry_count"], 0)

    def test_non_operating_event_row_is_skipped(self):
        view = build_week_view([sample(daily_schedule_id=None)],
                               date(2026, 12, 5))
        self.assertEqual(view["entry_count"], 0)

    def test_unassigned_truck_is_visible(self):
        view = build_week_view([sample(unit_id=None, unit_name=None)],
                               date(2026, 12, 5))
        item = view["days"][-1]["entries"][0]
        self.assertEqual(item["unit"], "No truck assigned")
        self.assertIsNone(item["event_unit_id"])

    def test_venue_and_location(self):
        view = build_week_view([sample()], date(2026, 12, 5))
        item = view["days"][-1]["entries"][0]
        self.assertEqual(item["venue"], "Downtown Square")
        self.assertEqual(item["location"], "Southlake, TX")

    def test_opening_time_sorting_before_unit_name(self):
        rows = [sample(unit_id=1, opens=22), sample(unit_id=2, opens=15)]
        view = build_week_view(rows, date(2026, 12, 5))
        items = view["days"][-1]["entries"]
        self.assertEqual([item["event_unit_id"] for item in items], [2, 1])

    def test_cancelled_status_kept_distinct_from_active(self):
        view = build_week_view([sample(event_status="cancelled")],
                               date(2026, 12, 5))
        day = view["days"][-1]
        self.assertEqual(day["assignment_count"], 1)
        self.assertEqual(day["active_assignment_count"], 0)
        self.assertTrue(day["entries"][0]["is_cancelled"])

    def test_invalid_color_falls_back_to_safe_color(self):
        view = build_week_view([sample(calendar_color="javascript:bad")],
                               date(2026, 12, 5))
        self.assertEqual(view["days"][-1]["entries"][0]["color"], "#64748B")

    def test_today_highlighting(self):
        view = build_week_view([], date(2026, 12, 5), date(2026, 12, 4))
        self.assertTrue(view["days"][5]["today"])
        self.assertFalse(view["days"][6]["today"])

    def test_readable_date_label_and_cross_month(self):
        view = build_week_view([], date(2026, 12, 2))
        self.assertEqual(view["label"], "November 29 – December 5, 2026")
        self.assertEqual(view["days"][0]["iso"], "2026-11-29")

    def test_cross_year_label(self):
        view = build_week_view([], date(2027, 1, 1))
        self.assertEqual(view["label"],
                         "December 27, 2026 – January 2, 2027")

    def test_previous_next_weeks_and_month_link_context(self):
        view = build_week_view([], date(2026, 12, 2))
        self.assertEqual(view["previous_date"], date(2026, 11, 22))
        self.assertEqual(view["next_date"], date(2026, 12, 6))
        self.assertEqual((view["year"], view["month"]), (2026, 12))

    def test_navigation_bounded_in_2000_and_2100(self):
        start = build_week_view([], date(2000, 1, 1))
        self.assertIsNone(start["previous_date"])
        finish = build_week_view([], date(2100, 12, 31))
        self.assertIsNone(finish["next_date"])

    def test_invalid_today_and_missing_rows_rejected(self):
        with self.assertRaises(EventWeekViewError):
            build_week_view([], date(2026, 12, 5), today="today")
        with self.assertRaises(EventWeekViewError):
            build_week_view(None, date(2026, 12, 5))

    def test_invalid_event_and_unit_ids_rejected(self):
        for row in (sample(event_id=True), sample(unit_id=-5)):
            with self.subTest(row=row), self.assertRaises(EventWeekViewError):
                build_week_view([row], date(2026, 12, 5))

    def test_datetime_operating_date_ignored(self):
        view = build_week_view([
            sample(operating_date=datetime(2026, 12, 5, 12))
        ], date(2026, 12, 5))
        self.assertEqual(view["entry_count"], 0)


if __name__ == "__main__":
    unittest.main()
