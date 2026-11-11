"""EC-063-4E: Copy date UX must not alter source event or save logic."""
import unittest
from pathlib import Path

FORM = Path(__file__).resolve().parents[1].joinpath(
    "templates/event_new.html"
).read_text()

class CopyDatePresentationTests(unittest.TestCase):
    def test_copy_date_mode_matches_full_height_fields(self):
        self.assertIn("#ec-copy-date-mode {", FORM)
        self.assertIn("min-height: 42px;", FORM)

    def test_end_date_remains_optional_and_unpopulated(self):
        self.assertIn('<input type="date" id="ec-copy-end" autocomplete="off"', FORM)
        self.assertNotIn('id="ec-copy-end" value=', FORM)
        self.assertIn('Leave empty to keep the original number of days.', FORM)

    def test_copy_end_date_has_accessible_help(self):
        self.assertIn('aria-describedby="ec-copy-end-help"', FORM)
        self.assertIn('id="ec-copy-end-help"', FORM)
        self.assertIn('id="ec-copy-calculated-end" role="status" aria-live="polite"', FORM)

    def test_safari_empty_placeholder_is_not_misleading(self):
        self.assertIn('copyEnd.classList.toggle("ec-copy-end-empty", !copyEnd.value)', FORM)
        self.assertIn('::-webkit-datetime-edit', FORM)
        self.assertIn('copyEnd.addEventListener("input", syncEmptyEndField)', FORM)

    def test_calculated_end_comes_from_server_prepared_draft(self):
        self.assertIn('const preparedEnd = parseDate(eventData.end_date);', FORM)
        self.assertIn('dateFormatter.format(preparedEnd)', FORM)
        self.assertIn('(calculated automatically)', FORM)

    def test_options_change_clears_previous_end_preview(self):
        self.assertIn('calculatedEnd.textContent =', FORM)
        self.assertIn('"The calculated end date will appear after Prepare Copy.";', FORM)
        self.assertIn('dateMode.addEventListener("change"', FORM)

    def test_custom_end_is_only_submitted_when_specified(self):
        self.assertIn('if (copyEnd.value) {', FORM)
        self.assertIn('options.target_end_date = copyEnd.value;', FORM)
        self.assertIn('options.target_start_date = copyStart.value;', FORM)

    def test_existing_create_edit_copy_save_boundaries_preserved(self):
        self.assertIn('"/events/" + copyEventId + "/copy-draft"', FORM)
        self.assertIn("url_for('save_peachpos_event')", FORM)
        self.assertIn('const isEditMode =', FORM)
        self.assertIn('const isCopyMode =', FORM)
        self.assertIn('Save as New Event', FORM)

if __name__ == '__main__':
    unittest.main()
