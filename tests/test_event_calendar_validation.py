import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from services.event_calendar_validation import (
    EventValidationError,
    validate_event_payload,
)

TZ = "America/Chicago"


def example_day(date="2026-11-14"):
    return {
        "date": date,
        "operating": True,
        "opens": "09:00",
        "closes": "18:00",
        "closes_next_day": False,
        "setup": "08:00",
        "breakdown": "19:00",
        "notes": "",
        "equipment_ids": ["1"],
        "shifts": [{
            "employee_id": "13",
            "starts": "10:00",
            "ends": "14:00",
            "ends_next_day": False,
            "equipment_id": "1",
            "role": "Lead",
            "notes": "",
        }],
    }


def example_payload():
    return {
        "event": {
            "name": "Hilltop Food Truck Park",
            "start_date": "2026-11-14",
            "end_date": "2026-11-14",
            "status": "scheduled",
            "include_on_peachweb": True,
            "venue_name": "Hilltop Food Truck Park",
            "street_address": "123 Main Street",
            "city": "Roanoke",
            "state": "TX",
            "zip_code": "76262",
            "permits_obtained": False,
        },
        "custom_values": {
            "1": "30 amp",
            "2": "B4",
            "3": "100",
        },
        "days": [example_day()],
    }


class EventSubmissionTests(unittest.TestCase):

    def valid(self, payload):
        return validate_event_payload(payload, TZ)

    def rejected(self, payload):
        with self.assertRaises(EventValidationError):
            self.valid(payload)

    def test_valid_event(self):
        result = self.valid(example_payload())
        self.assertEqual(len(result["days"]), 1)
        self.assertEqual(
            result["days"][0]["shifts"][0]["employee_id"],
            13
        )

    def test_missing_event_name(self):
        p = example_payload()
        p["event"]["name"] = ""
        self.rejected(p)

    def test_invalid_status(self):
        p = example_payload()
        p["event"]["status"] = "unknown"
        self.rejected(p)

    def test_invalid_visibility_boolean(self):
        p = example_payload()
        p["event"]["include_on_peachweb"] = "yes"
        self.rejected(p)

    def test_missing_date(self):
        p = example_payload()
        p["event"]["end_date"] = "2026-11-15"
        self.rejected(p)

    def test_duplicate_date(self):
        p = example_payload()
        p["days"].append(example_day())
        p["event"]["end_date"] = "2026-11-15"
        self.rejected(p)

    def test_duplicate_equipment(self):
        p = example_payload()
        p["days"][0]["equipment_ids"] = ["1", "1"]
        self.rejected(p)

    def test_unassigned_shift_equipment(self):
        p = example_payload()
        p["days"][0]["shifts"][0]["equipment_id"] = "2"
        self.rejected(p)

    def test_overlapping_shifts(self):
        p = example_payload()
        second = copy.deepcopy(p["days"][0]["shifts"][0])
        second["starts"] = "13:00"
        second["ends"] = "17:00"
        p["days"][0]["shifts"].append(second)
        self.rejected(p)

    def test_adjacent_shifts_allowed(self):
        p = example_payload()
        second = copy.deepcopy(p["days"][0]["shifts"][0])
        second["starts"] = "14:00"
        second["ends"] = "18:00"
        p["days"][0]["shifts"].append(second)
        self.assertEqual(
            len(self.valid(p)["days"][0]["shifts"]), 2
        )

    def test_cross_day_employee_overlap(self):
        p = example_payload()
        p["event"]["end_date"] = "2026-11-15"
        first = p["days"][0]["shifts"][0]
        first.update({
            "starts": "21:00",
            "ends": "02:00",
            "ends_next_day": True,
        })
        second_day = example_day("2026-11-15")
        second_day["shifts"][0].update({
            "starts": "01:00",
            "ends": "06:00",
        })
        p["days"].append(second_day)
        self.rejected(p)

    def test_cross_day_equipment_overlap(self):
        p = example_payload()
        p["event"]["end_date"] = "2026-11-15"
        first = p["days"][0]
        first.update({
            "opens": "21:00",
            "closes": "02:00",
            "closes_next_day": True,
            "setup": "",
            "breakdown": "",
            "shifts": [],
        })
        second = example_day("2026-11-15")
        second.update({
            "opens": "01:00",
            "closes": "06:00",
            "setup": "",
            "breakdown": "",
            "shifts": [],
        })
        p["days"].append(second)
        self.rejected(p)

    def test_nonoperating_day_cannot_have_shifts(self):
        p = example_payload()
        p["days"][0]["operating"] = False
        self.rejected(p)

    def test_invalid_employee_identifier(self):
        p = example_payload()
        p["days"][0]["shifts"][0]["employee_id"] = "-1"
        self.rejected(p)

    def test_nonexistent_dst_time(self):
        p = example_payload()
        p["event"]["start_date"] = "2026-03-08"
        p["event"]["end_date"] = "2026-03-08"
        day = p["days"][0]
        day["date"] = "2026-03-08"
        day["opens"] = "02:30"
        day["setup"] = ""
        self.rejected(p)

    def test_ambiguous_dst_time(self):
        p = example_payload()
        p["event"]["start_date"] = "2026-11-01"
        p["event"]["end_date"] = "2026-11-01"
        day = p["days"][0]
        day["date"] = "2026-11-01"
        day["opens"] = "01:30"
        day["setup"] = ""
        self.rejected(p)

    def test_invalid_contact_email(self):
        p = example_payload()
        p["event"]["contact_email"] = "not-an-email"
        self.rejected(p)



    def test_invalid_setup_clock_rejected(self):
        p = example_payload()
        p["days"][0]["setup"] = "29:00"
        self.rejected(p)

    def test_invalid_breakdown_clock_rejected(self):
        p = example_payload()
        p["days"][0]["breakdown"] = "99:00"
        self.rejected(p)

if __name__ == "__main__":
    unittest.main(verbosity=2)
