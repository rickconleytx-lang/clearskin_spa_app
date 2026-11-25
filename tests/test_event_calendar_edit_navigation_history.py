"""EC-062-14D-2: no-lease navigation and visible audit display."""
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
FORM = (ROOT / "templates/event_new.html").read_text()
CALENDAR = (ROOT / "templates/event_calendar_month.html").read_text()


class EditNavigationAndHistoryTests(unittest.TestCase):
    def test_edit_back_link_has_identity_and_normal_destination(self):
        self.assertIn('id="ec_back_to_calendar"', FORM)
        self.assertIn("url_for('peachpos_event_calendar_month')", FORM)
        self.assertIn('id="ec_cancel_edit"', FORM)

    def test_back_navigates_without_edit_lease(self):
        start = FORM.index('const backLink = document.getElementById("ec_back_to_calendar");')
        end = FORM.index('if (cancel) {', start)
        block = FORM[start:end]
        self.assertIn('event.preventDefault();', block)
        self.assertIn('window.location.assign("/events/calendar")', block)
        self.assertNotIn('edit-lock', block)

    def test_cancel_does_not_release_any_lease(self):
        self.assertNotIn('release.append("action", "release")', FORM)
        self.assertNotIn('sessionStorage', FORM)
        self.assertIn('window.location.assign("/events/calendar")', FORM)

    def test_top_history_is_edit_only(self):
        anchor = FORM.index('id="ec_edit_history_top"')
        self.assertIn('{% if event_edit_id %}', FORM[anchor - 120:anchor])
        self.assertIn('class="ec-edit-history-top"', FORM)
        self.assertIn('role="note" hidden', FORM)

    def test_top_history_is_server_sourced_and_text_only(self):
        self.assertIn('"/events/" + editEventId + "/details"', FORM)
        self.assertIn('method: "GET"', FORM)
        self.assertIn('savedEvent.event_id !== editEventId', FORM)
        self.assertIn('historyTop.textContent = savedEvent.history_text;', FORM)
        self.assertNotIn('historyTop.innerHTML', FORM)

    def test_modal_history_is_scoped_and_distinct(self):
        self.assertIn('history.classList.add("ec-detail-history")', CALENDAR)
        self.assertIn('#ec-detail-dialog .ec-detail-section.ec-detail-history', CALENDAR)
        self.assertIn('line(history, event.history_text', CALENDAR)

    def test_both_jinja_templates_still_parse(self):
        Environment().parse(FORM)
        Environment().parse(CALENDAR)


if __name__ == "__main__":
    unittest.main()
