"""EC-063 copy-draft safety and date-shift regression tests; no database."""
import copy
import unittest
from datetime import date, timedelta

from services.event_calendar_copy import (
    EventCopyInvalid, SECTION_DEFAULTS, build_event_copy_draft,
)


def sample(start="2026-11-18", span=2):
    beginning = date.fromisoformat(start)
    days = []
    for offset in range(span):
        current = (beginning + timedelta(days=offset)).isoformat()
        operating = offset == 0
        days.append({
            "date": current, "operating": operating,
            "opens": "11:00" if operating else None,
            "closes": "02:00" if operating else None,
            "closes_next_day": operating,
            "setup": "10:00" if operating else None,
            "breakdown": "03:00" if operating else None,
            "notes": "Daily note", "equipment_ids": [17] if operating else [],
            "shifts": [{"employee_id": 24, "starts": "12:00", "ends": "23:00",
                        "ends_next_day": False, "equipment_id": 17,
                        "role": "Driver", "notes": "Shift"}] if operating else [],
        })
    return {
        "event_id": 12, "event_revision": 4,
        "event": {
            "name": "Test Event", "start_date": start,
            "end_date": days[-1]["date"], "status": "confirmed",
            "include_on_peachweb": True, "permits_obtained": True,
            "public_description": "Public", "venue_name": "Venue",
            "street_address": "123 Main", "address_line2": "Suite 1",
            "city": "Northlake", "county": "Denton", "state": "TX",
            "zip_code": "76247", "parking_setup_location": "Rear",
            "contact_name": "Someone", "contact_phone": "555-0100",
            "contact_email": "a@example.com", "notes_1": "Note one",
            "notes_2": "Note two",
        },
        "custom_values": {"1": "Custom", "2": "", "3": ""},
        "days": days,
    }


class CopyDraftTests(unittest.TestCase):
    def test_default_next_week_date_range(self):
        result = build_event_copy_draft(sample())
        self.assertEqual(result["event"]["start_date"], "2026-11-25")
        self.assertEqual(result["event"]["end_date"], "2026-11-26")
        self.assertEqual([day["date"] for day in result["days"]],
                         ["2026-11-25", "2026-11-26"])

    def test_result_is_create_save_payload_only(self):
        result = build_event_copy_draft(sample())
        self.assertEqual(set(result), {"event", "custom_values", "days"})
        self.assertNotIn("event_id", result)
        self.assertNotIn("event_revision", result)

    def test_source_unchanged_and_result_independent(self):
        source = sample()
        original = copy.deepcopy(source)
        result = build_event_copy_draft(source)
        result["days"][0]["equipment_ids"].append(500)
        self.assertEqual(source, original)

    def test_safe_defaults(self):
        result = build_event_copy_draft(sample())
        self.assertEqual(result["event"]["status"], "scheduled")
        self.assertFalse(result["event"]["include_on_peachweb"])
        self.assertFalse(result["event"]["permits_obtained"])
        self.assertEqual(result["days"][0]["shifts"], [])
        self.assertEqual(result["event"]["contact_email"], "")

    def test_preserves_selected_location_notes_equipment_and_hours(self):
        result = build_event_copy_draft(sample())
        self.assertEqual(result["event"]["street_address"], "123 Main")
        self.assertEqual(result["event"]["notes_2"], "Note two")
        self.assertEqual(result["custom_values"]["1"], "Custom")
        self.assertEqual(result["days"][0]["opens"], "11:00")
        self.assertTrue(result["days"][0]["closes_next_day"])
        self.assertEqual(result["days"][0]["equipment_ids"], [17])
        self.assertFalse(result["days"][1]["operating"])

    def test_custom_start_preserves_span(self):
        result = build_event_copy_draft(sample(), target_start_date="2026-12-30")
        self.assertEqual(result["event"]["end_date"], "2026-12-31")

    def test_explicit_custom_date_range_expands_closed_days(self):
        result = build_event_copy_draft(sample(), target_start_date="2026-12-01",
                                        target_end_date="2026-12-04")
        self.assertEqual(len(result["days"]), 4)
        self.assertTrue(result["days"][0]["operating"])
        self.assertFalse(result["days"][2]["operating"])
        self.assertFalse(result["days"][3]["operating"])

    def test_explicit_custom_range_shorter(self):
        result = build_event_copy_draft(sample(), target_start_date="2026-12-01",
                                        target_end_date="2026-12-01")
        self.assertEqual(len(result["days"]), 1)

    def test_year_boundary(self):
        result = build_event_copy_draft(sample("2026-12-28"))
        self.assertEqual(result["event"]["start_date"], "2027-01-04")
        self.assertEqual(result["event"]["end_date"], "2027-01-05")

    def test_leap_day_shift(self):
        result = build_event_copy_draft(sample("2028-02-29"))
        self.assertEqual(result["event"]["start_date"], "2028-03-07")

    def test_copied_employees_must_be_explicitly_enabled(self):
        sections = dict(SECTION_DEFAULTS, employees=True)
        result = build_event_copy_draft(sample(), sections=sections)
        self.assertEqual(result["days"][0]["shifts"][0]["employee_id"], 24)
        self.assertEqual(result["days"][0]["shifts"][0]["equipment_id"], 17)

    def test_employees_without_equipment_become_unassigned(self):
        sections = dict(SECTION_DEFAULTS, employees=True, equipment=False)
        result = build_event_copy_draft(sample(), sections=sections)
        self.assertIsNone(result["days"][0]["shifts"][0]["equipment_id"])

    def test_permits_copied_only_explicitly(self):
        sections = dict(SECTION_DEFAULTS, permits=True)
        self.assertTrue(build_event_copy_draft(sample(), sections=sections)["event"]["permits_obtained"])

    def test_contact_copied_only_explicitly(self):
        sections = dict(SECTION_DEFAULTS, contacts=True)
        self.assertEqual(build_event_copy_draft(sample(), sections=sections)["event"]["contact_email"], "a@example.com")

    def test_uncheck_location_clears_private_address(self):
        sections = dict(SECTION_DEFAULTS, location=False)
        self.assertEqual(build_event_copy_draft(sample(), sections=sections)["event"]["street_address"], "")

    def test_uncheck_hours_requires_reentering_valid_hours(self):
        sections = dict(SECTION_DEFAULTS, daily_hours=False)
        result = build_event_copy_draft(sample(), sections=sections)
        self.assertTrue(result["days"][0]["operating"])
        self.assertIsNone(result["days"][0]["opens"])
        self.assertEqual(result["days"][0]["equipment_ids"], [])
        self.assertEqual(result["days"][0]["shifts"], [])

    def test_uncheck_notes_clears_daily_and_event_notes(self):
        sections = dict(SECTION_DEFAULTS, notes=False)
        result = build_event_copy_draft(sample(), sections=sections)
        self.assertEqual(result["event"]["notes_1"], "")
        self.assertEqual(result["days"][0]["notes"], "")

    def test_uncheck_custom_fields(self):
        sections = dict(SECTION_DEFAULTS, custom_fields=False)
        self.assertEqual(build_event_copy_draft(sample(), sections=sections)["custom_values"]["1"], "")

    def test_invalid_custom_dates_and_span(self):
        for start, end in [("2026-02-30", None), ("2026-12-02", "2026-12-01"),
                           ("2025-01-01", "2026-01-02"), ("2100-12-31", "2101-01-01")]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(EventCopyInvalid):
                    build_event_copy_draft(sample(), target_start_date=start, target_end_date=end)

    def test_invalid_boolean_sections_and_unknown_keys(self):
        for sections in (dict(SECTION_DEFAULTS, employees="true"),
                         dict(SECTION_DEFAULTS, invented=True), {}):
            with self.assertRaises(EventCopyInvalid):
                build_event_copy_draft(sample(), sections=sections)

    def test_reject_duplicate_or_missing_original_day(self):
        src = sample()
        src["days"][1]["date"] = src["days"][0]["date"]
        with self.assertRaises(EventCopyInvalid):
            build_event_copy_draft(src)

    def test_reject_bad_saved_identity(self):
        src = sample()
        src["event_id"] = -1
        with self.assertRaises(EventCopyInvalid):
            build_event_copy_draft(src)


if __name__ == "__main__":
    unittest.main()
