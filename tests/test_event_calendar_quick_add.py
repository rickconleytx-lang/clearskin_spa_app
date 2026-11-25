import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EventCalendarQuickAddTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.calendar = (
            ROOT / "templates/event_calendar_month.html"
        ).read_text()

        cls.form = (
            ROOT / "templates/event_new.html"
        ).read_text()

    def test_day_number_links_to_selected_date(self):
        self.assertIn(
            "href=\"{{ url_for('event_new', date=day.date.isoformat()) }}\"",
            self.calendar,
        )
        self.assertIn(
            '<a class="ec-month-day-number"',
            self.calendar,
        )

    def test_day_number_has_accessible_label(self):
        self.assertIn(
            'aria-label="Add event on ',
            self.calendar,
        )

    def test_normal_add_event_link_unchanged(self):
        self.assertIn(
            "href=\"{{ url_for('event_new') }}\"",
            self.calendar,
        )

    def test_form_has_both_date_inputs(self):
        self.assertIn('id="start_date"', self.form)
        self.assertIn('id="end_date"', self.form)

    def test_requested_date_is_validated(self):
        self.assertIn(
            'new URLSearchParams(window.location.search).get("date")',
            self.form,
        )
        self.assertIn(
            'if (!requestedDate || !parseDate(requestedDate))',
            self.form,
        )
        self.assertIn(
            'date.toISOString().slice(0, 10) !== value',
            self.form,
        )

    def test_both_dates_prefilled_and_schedule_rendered(self):
        self.assertRegex(
            self.form,
            r"startInput\.value = requestedDate;\s+"
            r"endInput\.value = requestedDate;\s+"
            r"renderDays\(\);",
        )

    def test_multi_day_dates_remain_editable(self):
        self.assertIn(
            'startInput.addEventListener("change", renderDays)',
            self.form,
        )
        self.assertIn(
            'endInput.addEventListener("change", renderDays)',
            self.form,
        )

    def test_existing_event_details_preserved(self):
        self.assertIn(
            'class="ec-month-event"',
            self.calendar,
        )
        self.assertIn(
            "peachpos_event_calendar_details",
            self.calendar,
        )
        self.assertIn(
            "openDetails(button);",
            self.calendar,
        )


if __name__ == "__main__":
    unittest.main()
