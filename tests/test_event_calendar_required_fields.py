"""Regression coverage for PeachPOS Add Event requirements.

Pure validation and template contract tests.
No application startup or database writes.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))

from services.event_calendar_validation import (
    EventValidationError,
    validate_event_payload,
)
from test_event_calendar_validation import (
    TZ,
    example_payload,
)


REQUIRED_TEXT = (
    ("name", "Event Name"),
    ("street_address", "Street Address"),
    ("city", "City"),
    ("state", "State"),
    ("zip_code", "ZIP Code"),
)

REQUIRED_INPUTS = (
    ("event_name", "Event Name"),
    ("start_date", "Start Date"),
    ("end_date", "End Date"),
    ("street_address", "Street Address"),
    ("city", "City"),
    ("state", "State"),
    ("zip_code", "ZIP Code"),
)


class EventRequiredFieldTests(unittest.TestCase):

    def reject_missing(self, field):
        payload = example_payload()
        payload["event"][field] = ""

        with self.assertRaisesRegex(
            EventValidationError,
            re.escape(field) + r": Required\."
        ):
            validate_event_payload(payload, TZ)

    def test_event_name_required(self):
        self.reject_missing("name")

    def test_street_address_required(self):
        self.reject_missing("street_address")

    def test_city_required(self):
        self.reject_missing("city")

    def test_state_required(self):
        self.reject_missing("state")

    def test_zip_code_required(self):
        self.reject_missing("zip_code")

    def test_start_date_required(self):
        payload = example_payload()
        payload["event"]["start_date"] = ""

        with self.assertRaises(EventValidationError):
            validate_event_payload(payload, TZ)

    def test_end_date_required(self):
        payload = example_payload()
        payload["event"]["end_date"] = ""

        with self.assertRaises(EventValidationError):
            validate_event_payload(payload, TZ)

    def test_whitespace_does_not_satisfy_required_fields(self):
        for field, _label in REQUIRED_TEXT:
            with self.subTest(field=field):
                payload = example_payload()
                payload["event"][field] = "   "

                with self.assertRaisesRegex(
                    EventValidationError,
                    re.escape(field) + r": Required\."
                ):
                    validate_event_payload(payload, TZ)

    def test_blank_venue_name_is_optional(self):
        payload = example_payload()
        payload["event"]["venue_name"] = ""

        result = validate_event_payload(payload, TZ)

        self.assertEqual(
            result["event"]["venue_name"], ""
        )

    def test_omitted_venue_name_is_optional(self):
        payload = example_payload()
        del payload["event"]["venue_name"]

        result = validate_event_payload(payload, TZ)

        self.assertEqual(
            result["event"]["venue_name"], ""
        )


class EventFormContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = (
            ROOT / "templates/event_new.html"
        ).read_text()

    def test_all_seven_fields_have_red_asterisks(self):
        for field, label in REQUIRED_INPUTS:
            with self.subTest(field=field):
                pattern = (
                    r'<label\s+for="' + re.escape(field) +
                    r'">\s*' + re.escape(label) +
                    r'\s*<span\s+'
                    r'style="color:\s*#c62828;\s*'
                    r'font-weight:\s*700;"\s+'
                    r'aria-hidden="true">\*</span>'
                    r'\s*</label>'
                )

                self.assertRegex(self.html, pattern)

        self.assertEqual(
            self.html.count(
                'style="color: #c62828; font-weight: 700;"'
            ),
            7
        )

    def test_all_seven_inputs_are_required(self):
        for field, _label in REQUIRED_INPUTS:
            with self.subTest(field=field):
                pattern = (
                    r'<input\b(?=[^>]*\bid="' +
                    re.escape(field) +
                    r'")[^>]*>'
                )

                matches = re.findall(
                    pattern, self.html, re.DOTALL
                )

                self.assertEqual(len(matches), 1)

                self.assertRegex(
                    matches[0],
                    r'\srequired(?:\s|>)'
                )
                self.assertIn(
                    'aria-required="true"',
                    matches[0]
                )

    def test_review_appears_before_save(self):
        review = self.html.index(
            'id="ec_preview_payload"'
        )
        feedback = self.html.index(
            'id="ec_payload_summary"'
        )
        save = self.html.index(
            'id="ec_save_event"'
        )

        self.assertLess(review, feedback)
        self.assertLess(feedback, save)

        self.assertIn(
            "Step 1 — Review Your Event",
            self.html
        )
        self.assertIn(
            "Step 2 — Save Your Event",
            self.html
        )
        self.assertIn(
            "Review Event Details",
            self.html
        )

    def test_browser_checks_required_fields(self):
        self.assertEqual(
            self.html.count(
                "firstMissingRequiredEventField()"
            ),
            3
        )

        for field, label in REQUIRED_INPUTS:
            with self.subTest(field=field):
                self.assertIn(
                    f'["{field}", "{label}"]',
                    self.html
                )

        self.assertIn(
            '"REVIEW FAILED — "',
            self.html
        )

    def test_save_submission_contract_preserved(self):
        self.assertEqual(
            self.html.count(
                'transport.addEventListener("submit"'
            ),
            1
        )

        self.assertEqual(
            self.html.count(
                "url_for('save_peachpos_event')"
            ),
            2
        )

        for marker in (
            'id="ec_event_transport"',
            'id="ec_submission_token"',
            'id="ec_save_event"',
            'name="security_csrf_token"',
            "window.crypto.randomUUID()",
            "if (saveDispatched && !definiteRejection) {",
        ):
            self.assertIn(marker, self.html)

        self.assertNotIn(
            "Review Captured Event Data",
            self.html
        )


if __name__ == "__main__":
    unittest.main()
