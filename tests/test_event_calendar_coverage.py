import unittest
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from services.event_calendar_validation import (
    validate_event_payload,
)
from services.event_calendar_coverage import (
    analyze_event_coverage,
)

TZ = "America/Chicago"


def shift(employee, start, end, unit="101", overnight=False):
    return {
        "employee_id": str(employee),
        "starts": start,
        "ends": end,
        "ends_next_day": overnight,
        "equipment_id": unit,
        "role": "",
        "notes": "",
    }


def day(date="2026-11-14", **overrides):
    result = {
        "date": date,
        "operating": True,
        "opens": "10:00",
        "closes": "18:00",
        "closes_next_day": False,
        "setup": "",
        "breakdown": "",
        "notes": "",
        "equipment_ids": ["101"],
        "shifts": [],
    }
    result.update(overrides)
    return result


def analyze(*days):
    dates = sorted(item["date"] for item in days)

    payload = {
        "event": {
            "name": "Coverage Test Event",
            "venue_name": "Test Venue",
            "street_address": "123 Main Street",
            "city": "Roanoke",
            "state": "TX",
            "zip_code": "76262",
            "status": "scheduled",
            "include_on_peachweb": False,
            "permits_obtained": False,
            "start_date": dates[0],
            "end_date": dates[-1],
        },
        "custom_values": {},
        "days": list(days),
    }

    normalized = validate_event_payload(payload, TZ)
    return analyze_event_coverage(normalized)


def coverage(result, day_index=0, unit_index=0):
    return result["days"][day_index]["unit_coverage"][unit_index]


class EventCoverageTests(unittest.TestCase):

    def test_rick_leaves_two_hour_gap(self):
        result = analyze(day(shifts=[
            shift(13, "10:00", "16:00")
        ]))
        item = coverage(result)

        self.assertEqual(item["status"], "partial")
        self.assertEqual(item["covered_minutes"], 360)
        self.assertEqual(item["uncovered_minutes"], 120)
        self.assertTrue(
            item["gaps"][0]["starts_at"].endswith(
                "22:00:00+00:00"
            )
        )

    def test_two_workers_cover_entire_day(self):
        result = analyze(day(shifts=[
            shift(13, "10:00", "14:00"),
            shift(14, "14:00", "18:00"),
        ]))
        self.assertEqual(coverage(result)["status"], "covered")
        self.assertEqual(result["uncovered_unit_days"], 0)

    def test_no_workers(self):
        result = analyze(day())
        item = coverage(result)
        self.assertEqual(item["status"], "no_staff")
        self.assertEqual(item["uncovered_minutes"], 480)

    def test_gap_between_workers(self):
        result = analyze(day(shifts=[
            shift(13, "10:00", "12:00"),
            shift(14, "14:00", "18:00"),
        ]))
        item = coverage(result)
        self.assertEqual(item["uncovered_minutes"], 120)
        self.assertEqual(len(item["gaps"]), 1)

    def test_start_of_day_gap(self):
        result = analyze(day(shifts=[
            shift(13, "12:00", "18:00"),
        ]))
        self.assertEqual(
            coverage(result)["uncovered_minutes"], 120
        )

    def test_two_trucks_checked_separately(self):
        result = analyze(day(
            equipment_ids=["101", "102"],
            shifts=[shift(13, "10:00", "18:00", "101")],
        ))
        units = result["days"][0]["unit_coverage"]

        self.assertEqual(units[0]["unit_id"], 101)
        self.assertEqual(units[0]["status"], "covered")
        self.assertEqual(units[1]["unit_id"], 102)
        self.assertEqual(units[1]["status"], "no_staff")
        self.assertEqual(result["uncovered_unit_days"], 1)

    def test_unassigned_shift_does_not_staff_truck(self):
        result = analyze(day(shifts=[
            shift(13, "10:00", "18:00", None)
        ]))
        self.assertEqual(coverage(result)["status"], "no_staff")
        self.assertEqual(
            result["days"][0]["unassigned_shift_count"], 1
        )

    def test_event_without_truck_uses_general_shifts(self):
        result = analyze(day(
            equipment_ids=[],
            shifts=[shift(13, "10:00", "18:00", None)],
        ))
        self.assertEqual(coverage(result)["unit_id"], None)
        self.assertEqual(coverage(result)["status"], "covered")

    def test_overnight_partial_coverage(self):
        result = analyze(day(
            opens="21:00",
            closes="02:00",
            closes_next_day=True,
            shifts=[
                shift(13, "21:00", "00:00",
                      overnight=True),
            ],
        ))
        item = coverage(result)
        self.assertEqual(item["uncovered_minutes"], 120)
        self.assertEqual(item["status"], "partial")

    def test_overnight_handoff(self):
        result = analyze(day(
            opens="21:00",
            closes="02:00",
            closes_next_day=True,
            shifts=[
                shift(13, "21:00", "23:00"),
                shift(14, "23:00", "02:00",
                      overnight=True),
            ],
        ))
        self.assertEqual(coverage(result)["status"], "covered")

    def test_prior_day_shift_extends_into_next_day(self):
        saturday = day(
            "2026-11-14",
            opens="21:00",
            closes="02:00",
            closes_next_day=True,
            shifts=[
                shift(13, "21:00", "03:00",
                      overnight=True),
            ],
        )
        sunday = day(
            "2026-11-15",
            opens="02:00",
            closes="06:00",
        )
        result = analyze(saturday, sunday)

        self.assertEqual(
            coverage(result, 1)["covered_minutes"], 60
        )
        self.assertEqual(
            coverage(result, 1)["uncovered_minutes"], 180
        )

    def test_nonoperating_day_skipped(self):
        result = analyze(
            day("2026-11-14"),
            day(
                "2026-11-15",
                operating=False,
                equipment_ids=[],
            ),
        )
        self.assertEqual(len(result["days"]), 1)

    def test_daylight_saving_uses_elapsed_minutes(self):
        result = analyze(day(
            "2026-11-01",
            opens="00:30",
            closes="02:30",
            shifts=[
                shift(13, "00:30", "02:30"),
            ],
        ))
        item = coverage(result)
        self.assertEqual(item["required_minutes"], 180)
        self.assertEqual(item["status"], "covered")

    def test_outside_hours_are_clipped(self):
        result = analyze(day(shifts=[
            shift(13, "09:00", "12:00"),
        ]))
        item = coverage(result)
        self.assertEqual(item["covered_minutes"], 120)
        self.assertEqual(item["uncovered_minutes"], 360)


if __name__ == "__main__":
    unittest.main(verbosity=2)
