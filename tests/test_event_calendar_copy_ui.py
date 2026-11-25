"""EC-063-3C: Copy Event UI and Create/Edit isolation contracts."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = (ROOT / "templates/event_calendar_month.html").read_text()
FORM = (ROOT / "templates/event_new.html").read_text()
APP = (ROOT / "app.py").read_text()

class CopyEventUIContracts(unittest.TestCase):
    def test_calendar_modal_has_separate_copy_button(self):
        self.assertIn('id="ec-detail-copy"', CALENDAR)
        self.assertIn('hidden>Copy Event</button>', CALENDAR)
        self.assertIn('editUrl.searchParams.set("edit"', CALENDAR)
        self.assertIn('copyUrl.searchParams.set("copy"', CALENDAR)

    def test_copy_button_requires_loaded_event(self):
        self.assertIn('copyButton.hidden = true;', CALENDAR)
        self.assertIn('copyButton.hidden = false;', CALENDAR)
        self.assertIn('!activeEventId || !activeEventButton || !dialog.open', CALENDAR)

    def test_copy_route_is_mutually_exclusive_with_edit(self):
        tree = ast.parse(APP)
        node = next(x for x in tree.body if isinstance(x, ast.FunctionDef)
                    and x.name == 'event_new')
        text = ast.get_source_segment(APP, node)
        self.assertIn('if edit_raw is not None and copy_raw is not None:', text)
        self.assertIn('abort(404)', text)
        self.assertIn('event_copy_id=copy_event_id', text)

    def test_copy_start_is_new_event_not_edit(self):
        self.assertIn('const isCopyMode = Number.isSafeInteger(copyEventId)', FORM)
        self.assertIn('if (!isEditMode && transport && saveButton', FORM)
        self.assertIn('"Save as New Event"', FORM)
        self.assertIn('if (isCopyMode && !copyDraftReady)', FORM)
        self.assertIn("url_for('save_peachpos_event')", FORM)

    def test_copy_requires_server_read_and_csrf(self):
        self.assertIn('"/events/" + copyEventId + "/copy-draft"', FORM)
        self.assertIn('body.append("security_csrf_token", csrf.value);', FORM)
        self.assertIn('body.append("copy_options", JSON.stringify(options));', FORM)
        self.assertIn('result.source_event_id !== copyEventId', FORM)

    def test_copy_only_on_prepare_action(self):
        self.assertIn('prepare.addEventListener("click", async function ()', FORM)
        self.assertIn('copyDraftReady = false;', FORM)
        self.assertIn('preview.disabled = false;', FORM)
        self.assertIn('save.disabled = false;', FORM)

    def test_default_section_flags(self):
        for key in ('event_details', 'location', 'daily_hours', 'equipment',
                    'notes', 'custom_fields'):
            self.assertIn(f'data-copy-section="{key}" checked', FORM)
        for key in ('contacts', 'employees', 'permits'):
            self.assertIn(f'data-copy-section="{key}">', FORM)

    def test_week_and_custom_dates(self):
        self.assertIn('<option value="next_week" selected>', FORM)
        self.assertIn('<option value="custom">', FORM)
        self.assertIn('options.target_start_date = copyStart.value;', FORM)
        self.assertIn('options.target_end_date = copyEnd.value;', FORM)

    def test_original_source_not_sent_to_save(self):
        self.assertIn('draft.event_id != null', FORM)
        self.assertIn('result.saved !== false', FORM)
        self.assertIn('"event_payload", serialized', FORM)

    def test_reuse_existing_scheduling_form(self):
        self.assertIn('dailyValues.clear();', FORM)
        self.assertIn('renderDays();', FORM)
        self.assertIn('"input[data-event-unit-id]"', FORM)
        self.assertIn('availableEmployeeIds', FORM)

    def test_quick_add_and_edit_not_affected(self):
        self.assertIn('if (isEditMode) return;', FORM)
        self.assertIn('if (isCopyMode) return;', FORM)
        self.assertIn('"/events/" + editEventId + "/edit-draft"', FORM)
        self.assertIn('"/events/" + editEventId + "/edit-save-unlocked"', FORM)

if __name__ == '__main__':
    unittest.main()
