import unittest

from datetime import date, datetime, timezone

from services.peachweb_event_schedule import (
    five_week_windows,
    format_week_heading,
)


class PeachWebEventScheduleTests(unittest.TestCase):

    def test_five_consecutive_monday_sunday_weeks(self):
        now = datetime(
            2026, 11, 14, 18, 0, tzinfo=timezone.utc
        )
        weeks = five_week_windows(
            "America/Chicago", now=now
        )

        self.assertEqual(len(weeks), 5)
        self.assertEqual(weeks[0], (
            date(2026, 11, 9), date(2026, 11, 15)
        ))
        self.assertEqual(weeks[-1], (
            date(2026, 12, 7), date(2026, 12, 13)
        ))

        for start, end in weeks:
            self.assertEqual(start.weekday(), 0)
            self.assertEqual(end.weekday(), 6)

    def test_automatic_monday_rollover(self):
        before = datetime(
            2026, 11, 16, 5, 59, tzinfo=timezone.utc
        )
        after = datetime(
            2026, 11, 16, 6, 0, tzinfo=timezone.utc
        )

        old = five_week_windows(
            "America/Chicago", now=before
        )
        new = five_week_windows(
            "America/Chicago", now=after
        )

        self.assertEqual(old[0][0], date(2026, 11, 9))
        self.assertEqual(new[0][0], date(2026, 11, 16))
        self.assertEqual(new[0], old[1])

    def test_month_boundary_remains_one_week(self):
        weeks = five_week_windows(
            "America/Chicago",
            now=datetime(
                2026, 11, 30, 18, tzinfo=timezone.utc
            ),
        )

        self.assertEqual(
            weeks[0],
            (date(2026, 11, 30), date(2026, 12, 6)),
        )
        self.assertEqual(
            format_week_heading(*weeks[0]),
            "November 30 – December 6",
        )

    def test_year_boundary_remains_one_week(self):
        self.assertEqual(
            format_week_heading(
                date(2026, 12, 28),
                date(2027, 1, 3),
            ),
            "December 28, 2026 – January 3, 2027",
        )

    def test_business_timezone_controls_rollover(self):
        instant = datetime(
            2026, 11, 16, 5, 30, tzinfo=timezone.utc
        )

        chicago = five_week_windows(
            "America/Chicago", now=instant
        )
        new_york = five_week_windows(
            "America/New_York", now=instant
        )

        self.assertEqual(chicago[0][0], date(2026, 11, 9))
        self.assertEqual(new_york[0][0], date(2026, 11, 16))

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            five_week_windows(
                "America/Chicago",
                now=datetime(2026, 11, 14, 12),
            )

    def test_missing_timezone_is_rejected(self):
        with self.assertRaises(ValueError):
            five_week_windows("")

    def test_invalid_week_heading_is_rejected(self):
        with self.assertRaises(ValueError):
            format_week_heading(
                date(2026, 11, 3),
                date(2026, 11, 9),
            )


if __name__ == "__main__":
    unittest.main()
