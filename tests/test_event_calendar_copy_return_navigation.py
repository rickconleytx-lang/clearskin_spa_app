"""EC-063-3G: Post-save fresh calendar navigation for Create and Copy Event."""
import unittest
from pathlib import Path

FORM = Path(__file__).resolve().parents[1].joinpath(
    "templates/event_new.html"
).read_text()

class CopyReturnCalendarContract(unittest.TestCase):
    def test_return_link_is_hidden_until_success(self):
        self.assertIn('<p id="ec_new_event_link" hidden>', FORM)
        self.assertIn('id="ec_return_to_calendar_after_save"', FORM)
        self.assertIn('Return to Event Calendar', FORM)
        self.assertIn('newEventLink.hidden = false;', FORM)

    def test_return_link_stays_in_confirmed_success_branch(self):
        beginning = FORM.index('if (\n                    response.ok &&\n                    result.ok === true &&\n                    result.saved === true &&')
        end = FORM.index('if (\n                    [400, 403, 409, 413, 422]', beginning)
        success = FORM[beginning:end]
        self.assertIn('saveCompleted = true;', success)
        self.assertIn('newEventLink.hidden = false;', success)
        self.assertIn('calendarUrl.searchParams.set(', success)

    def test_link_targets_saved_event_month(self):
        self.assertIn('JSON.parse(pendingSavePayload)', FORM)
        self.assertIn('savedDraft.event.start_date', FORM)
        self.assertIn('calendarUrl.searchParams.set("year", dateParts[1]);', FORM)
        self.assertIn('"month", String(Number(dateParts[2]))', FORM)

    def test_unique_saved_event_query_prevents_stale_back_link(self):
        self.assertIn('"saved_event_id", String(result.event_id)', FORM)
        self.assertIn('returnLink.href = calendarUrl.href;', FORM)
        self.assertNotIn('window.history.back()', FORM)

    def test_create_another_event_remains_available(self):
        self.assertIn('Create Another Event', FORM)
        self.assertIn('href="{{ url_for(\'event_new\') }}"', FORM)

    def test_create_save_endpoint_and_duplicate_safeguard_unchanged(self):
        self.assertIn("url_for('save_peachpos_event')", FORM)
        self.assertIn('result.duplicate', FORM)
        self.assertIn('saveCompleted = true;', FORM)

    def test_edit_and_copy_modes_remain_separate(self):
        self.assertIn('const isEditMode =', FORM)
        self.assertIn('const isCopyMode =', FORM)
        self.assertIn('if (!isEditMode && transport && saveButton', FORM)

if __name__ == "__main__":
    unittest.main()
