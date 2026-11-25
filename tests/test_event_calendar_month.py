"""Pure Month-view model and route-contract regression tests."""

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.event_calendar_month import (
    build_month_view,
    format_event_clock,
    readable_text_color,
)


def event_row(day=date(2026, 11, 18), unit_id=2):
    return {
        "event_id": 12,
        "event_name": "EC-050G Safari Save Test",
        "start_date": day,
        "end_date": day,
        "event_status": "scheduled",
        "venue_name": "PeachPOS Test Location",
        "city": "Northlake",
        "state": "TX",
        "timezone_name": "America/Chicago",
        "daily_schedule_id": 101,
        "operating_date": day,
        "opens_at": datetime(
            2026, 11, 18, 17, 0, tzinfo=timezone.utc
        ),
        "closes_at": datetime(
            2026, 11, 18, 20, 0, tzinfo=timezone.utc
        ),
        "event_unit_id": unit_id,
        "unit_name": "Large Truck - CDL",
        "calendar_color": "#00f900",
    }


class EventCalendarMonthTests(unittest.TestCase):

    def test_saved_event_appears_on_november_18(self):
        calendar = build_month_view(
            [event_row()], 2026, 11,
            today=date(2026, 11, 10)
        )

        days = [
            day for week in calendar["weeks"] for day in week
            if day["date"] == date(2026, 11, 18)
        ]

        self.assertEqual(len(days), 1)
        self.assertEqual(len(days[0]["entries"]), 1)
        self.assertEqual(
            days[0]["entries"][0]["event_id"], 12
        )
        self.assertEqual(
            days[0]["entries"][0]["color"], "#00f900"
        )
        self.assertEqual(calendar["entry_count"], 1)

    def test_bright_green_gets_dark_text(self):
        self.assertEqual(
            readable_text_color("#00f900"), "#17212B"
        )

    def test_dark_navy_gets_white_text(self):
        self.assertEqual(
            readable_text_color("#152637"), "#FFFFFF"
        )

    def test_white_background_gets_dark_text(self):
        self.assertEqual(
            readable_text_color("#FFFFFF"), "#17212B"
        )

    def test_utc_hours_display_in_chicago_time(self):
        self.assertEqual(
            format_event_clock(
                event_row()["opens_at"], "America/Chicago"
            ),
            "11:00 AM",
        )

    def test_multi_day_event_appears_on_both_operating_days(self):
        first = event_row()
        second = event_row(date(2026, 11, 19))
        second["daily_schedule_id"] = 102

        calendar = build_month_view(
            [first, second], 2026, 11
        )

        self.assertEqual(calendar["entry_count"], 2)

    def test_nonoperating_day_does_not_create_event_chip(self):
        row = event_row()
        row["daily_schedule_id"] = None
        row["operating_date"] = None

        calendar = build_month_view([row], 2026, 11)

        self.assertEqual(calendar["entry_count"], 0)

    def test_duplicate_event_unit_rows_display_once(self):
        row = event_row()

        calendar = build_month_view(
            [row, row.copy()], 2026, 11
        )

        self.assertEqual(calendar["entry_count"], 1)

    def test_invalid_month_rejected(self):
        for year, month in (
            (2026, 0),
            (2026, 13),
            (1999, 11),
            (True, 11),
        ):
            with self.subTest(year=year, month=month):
                with self.assertRaises(ValueError):
                    build_month_view([], year, month)

    def test_route_is_separate_and_protected(self):
        source = (ROOT / "app.py").read_text()
        start = source.index(
            '@app.route("/events/calendar", methods=["GET"])'
        )
        end = source.index(
            'def peachpos_event_calendar_month():',
            start
        )

        decorators = source[start:end]

        for required in (
            "@login_required",
            "@spa_required",
            '@require_subscription_feature("event_calendar")',
            '@require_workspace_permission("can_manage_event_units")',
        ):
            self.assertIn(required, decorators)

        self.assertIn(
            'cur.execute("SET TRANSACTION READ ONLY")',
            source[start:]
        )

    def test_month_template_preserves_navigation(self):
        source = (
            ROOT / "templates/event_calendar_month.html"
        ).read_text()

        self.assertIn(
            "url_for('peachpos_event_calendar_month'",
            source
        )
        self.assertIn("url_for('event_new')", source)
        self.assertIn("{{ item.color }}", source)
        self.assertIn("{{ item.name }}", source)
        self.assertIn("{{ item.hours }}", source)


if __name__ == "__main__":
    unittest.main()
