import sys
import unittest
from pathlib import Path
from datetime import timedelta

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from services.event_calendar_time import (
    EventTimeError,
    parse_event_date,
    parse_event_time,
    event_time_interval,
    intervals_overlap,
)

TZ = "America/Chicago"


class EventCalendarTimeTests(unittest.TestCase):

    def interval(self, day, start, end, overnight=False):
        return event_time_interval(
            day, start, end, overnight, TZ
        )

    def test_normal_day(self):
        start, end = self.interval(
            "2026-11-14", "10:00", "18:00"
        )
        self.assertEqual(end - start, timedelta(hours=8))

    def test_overnight(self):
        start, end = self.interval(
            "2026-11-14", "21:00", "02:00", True
        )
        self.assertEqual(end - start, timedelta(hours=5))

    def test_adjacent_shifts(self):
        a, b = self.interval(
            "2026-11-14", "09:00", "15:00"
        )
        c, d = self.interval(
            "2026-11-14", "15:00", "18:00"
        )
        self.assertFalse(intervals_overlap(a, b, c, d))

    def test_same_day_overlap(self):
        a, b = self.interval(
            "2026-11-14", "09:00", "15:00"
        )
        c, d = self.interval(
            "2026-11-14", "13:00", "18:00"
        )
        self.assertTrue(intervals_overlap(a, b, c, d))

    def test_cross_day_overlap(self):
        a, b = self.interval(
            "2026-11-14", "21:00", "02:00", True
        )
        c, d = self.interval(
            "2026-11-15", "01:00", "06:00"
        )
        self.assertTrue(intervals_overlap(a, b, c, d))

    def test_spring_forward_elapsed_time(self):
        start, end = self.interval(
            "2026-03-08", "01:30", "03:30"
        )
        self.assertEqual(end - start, timedelta(hours=1))

    def test_fall_back_elapsed_time(self):
        start, end = self.interval(
            "2026-11-01", "00:30", "02:30"
        )
        self.assertEqual(end - start, timedelta(hours=3))

    def test_nonexistent_spring_time_rejected(self):
        with self.assertRaises(EventTimeError):
            self.interval(
                "2026-03-08", "02:30", "04:00"
            )

    def test_ambiguous_fall_time_rejected(self):
        with self.assertRaises(EventTimeError):
            self.interval(
                "2026-11-01", "01:30", "02:30"
            )

    def test_invalid_overnight_flag(self):
        with self.assertRaises(EventTimeError):
            self.interval(
                "2026-11-14", "21:00", "02:00"
            )

    def test_over_24_hours_rejected(self):
        with self.assertRaises(EventTimeError):
            self.interval(
                "2026-11-14", "09:00", "10:00", True
            )

    def test_bad_date_rejected(self):
        with self.assertRaises(EventTimeError):
            parse_event_date("2026-02-30")

    def test_bad_clock_rejected(self):
        with self.assertRaises(EventTimeError):
            parse_event_time("25:00")

    def test_unknown_timezone_rejected(self):
        with self.assertRaises(EventTimeError):
            event_time_interval(
                "2026-11-14", "09:00", "10:00",
                False, "Invalid/Timezone"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
