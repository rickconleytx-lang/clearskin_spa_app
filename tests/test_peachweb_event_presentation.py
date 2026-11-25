import unittest

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from services.peachweb_event_presentation import (
    build_weekly_public_schedule,
)
from services.peachweb_event_schedule import five_week_windows


ZONE = ZoneInfo("America/Chicago")


def event_day(
    day,
    opening,
    closing,
    *,
    event_id=3,
    name="HillTop Truck Park",
    city="Northlake",
    street="100 Main Street",
):
    end_day = day

    if closing <= opening:
        end_day += timedelta(days=1)

    start = datetime.combine(
        day, time(opening), tzinfo=ZONE
    ).astimezone(timezone.utc)

    end = datetime.combine(
        end_day, time(closing), tzinfo=ZONE
    ).astimezone(timezone.utc)

    return {
        "event_id": event_id,
        "event_name": name,
        "venue_name": name,
        "city": city,
        "state": "TX",
        "street_address": street,
        "address_line2": None,
        "zip_code": "76247",
        "timezone_name": "America/Chicago",
        "operating_date": day,
        "opens_at": start,
        "closes_at": end,
    }


class PeachWebPresentationTests(unittest.TestCase):

    def setUp(self):
        self.windows = five_week_windows(
            "America/Chicago",
            now=datetime(
                2026, 11, 16, 18,
                tzinfo=timezone.utc,
            ),
        )

    def render(self, rows, **options):
        return build_weekly_public_schedule(
            rows, self.windows, **options
        )

    def test_empty_weeks_are_hidden(self):
        self.assertEqual(self.render([]), [])

    def test_one_event_multiple_days_one_line(self):
        rows = [
            event_day(date(2026, 11, 20), 11, 20),
            event_day(date(2026, 11, 21), 10, 21),
            event_day(date(2026, 11, 22), 11, 17),
        ]

        result = self.render(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["events"]), 1)
        self.assertEqual(
            result[0]["events"][0]["hours"],
            "Fri: 11–8 / Sat: 10–9 / Sun: 11–5",
        )

    def test_consecutive_identical_hours_combine(self):
        rows = [
            event_day(
                date(2026, 11, 16) + timedelta(days=i),
                11, 19,
            )
            for i in range(5)
        ]

        result = self.render(rows)

        self.assertEqual(
            result[0]["events"][0]["hours"],
            "Mon–Fri: 11–7",
        )

    def test_nonconsecutive_days_do_not_combine(self):
        rows = [
            event_day(date(2026, 11, 16), 11, 19),
            event_day(date(2026, 11, 18), 11, 19),
        ]

        self.assertEqual(
            self.render(rows)[0]["events"][0]["hours"],
            "Mon: 11–7 / Wed: 11–7",
        )

    def test_multweek_event_is_split_by_week(self):
        rows = [
            event_day(
                date(2026, 11, 20) + timedelta(days=i),
                11, 19,
            )
            for i in range(5)
        ]

        result = self.render(rows)

        self.assertEqual(len(result), 2)
        self.assertEqual(
            result[0]["events"][0]["hours"],
            "Fri–Sun: 11–7",
        )
        self.assertEqual(
            result[1]["events"][0]["hours"],
            "Mon–Tue: 11–7",
        )

    def test_month_transition_remains_one_week(self):
        rows = [
            event_day(date(2026, 11, 30), 11, 19),
            event_day(date(2026, 12, 1), 11, 19),
        ]

        result = self.render(rows)

        self.assertEqual(
            result[0]["heading"],
            "November 30 – December 6",
        )
        self.assertEqual(
            result[0]["events"][0]["hours"],
            "Mon–Tue: 11–7",
        )

    def test_outside_window_does_not_appear(self):
        rows = [
            event_day(date(2026, 11, 15), 11, 19),
            event_day(date(2026, 12, 21), 11, 19),
        ]

        self.assertEqual(self.render(rows), [])

    def test_directions_use_public_address(self):
        row = event_day(date(2026, 11, 16), 11, 19)

        event = self.render([row])[0]["events"][0]

        self.assertIn(
            "google.com/maps/search/",
            event["directions_url"],
        )
        self.assertIn(
            "100+Main+Street",
            event["directions_url"],
        )

    def test_directions_can_be_disabled(self):
        row = event_day(date(2026, 11, 16), 11, 19)

        event = self.render(
            [row], show_directions=False
        )[0]["events"][0]

        self.assertIsNone(event["directions_url"])

    def test_missing_address_has_no_directions(self):
        row = event_day(
            date(2026, 11, 16),
            11, 19, street=""
        )

        event = self.render([row])[0]["events"][0]

        self.assertIsNone(event["directions_url"])

    def test_hours_can_be_disabled(self):
        row = event_day(date(2026, 11, 16), 11, 19)

        event = self.render(
            [row], show_hours=False
        )[0]["events"][0]

        self.assertEqual(event["hours"], "")

    def test_overnight_hours_are_explicit(self):
        row = event_day(date(2026, 11, 20), 18, 2)

        event = self.render([row])[0]["events"][0]

        self.assertEqual(
            event["hours"],
            "Fri: 6p–2a (+1 day)",
        )

    def test_public_output_has_no_admin_fields(self):
        row = event_day(date(2026, 11, 16), 11, 19)
        row["contact_email"] = "private@example.com"
        row["notes_1"] = "Private note"

        event = self.render([row])[0]["events"][0]

        self.assertEqual(
            set(event),
            {"name", "city", "hours", "directions_url"},
        )
        self.assertNotIn("contact_email", event)
        self.assertNotIn("notes_1", event)

    def test_duplicate_event_day_rejected(self):
        row = event_day(date(2026, 11, 16), 11, 19)

        with self.assertRaises(ValueError):
            self.render([row, row])


if __name__ == "__main__":
    unittest.main()
