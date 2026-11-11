"""Event Edit interface contracts at preview stage."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class EventEditUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.py").read_text()
        cls.calendar = (ROOT / "templates/event_calendar_month.html").read_text()
        cls.form = (ROOT / "templates/event_new.html").read_text()

    def test_calendar_receives_csrf(self):
        self.assertIn('event_csrf_token=_security_form_csrf_token()', self.app)
        self.assertIn('id="ec-calendar-edit-csrf"', self.calendar)

    def test_edit_button_and_lock_url(self):
        self.assertIn('id="ec-detail-edit"', self.calendar)
        self.assertIn('data-edit-lock-url=', self.calendar)

    def test_acquire_via_post(self):
        self.assertIn('data.append("action", "acquire")', self.calendar)
        self.assertIn('method: "POST"', self.calendar)

    def test_token_not_in_url(self):
        self.assertIn('sessionStorage.setItem(key', self.calendar)
        self.assertIn('searchParams.set("edit"', self.calendar)
        self.assertNotIn('searchParams.set("lock_token"', self.calendar)

    def test_busy_editor_status(self):
        self.assertIn('result.status === "busy"', self.calendar)
        self.assertIn('result.editor_display_name', self.calendar)

    def test_edit_mode_disables_create_save_handler(self):
        self.assertIn('if (!isEditMode && transport && saveButton', self.form)
        self.assertIn('action="{% if event_edit_id %}#', self.form)

    def test_save_changes_disabled(self):
        self.assertIn('Save Changes (Not Yet Available)', self.form)
        self.assertIn('{% if event_edit_id %}disabled{% endif %}', self.form)

    def test_daily_values_prefilled(self):
        self.assertIn('dailyValues.clear();', self.form)
        self.assertIn('dailyValues.set(date, value);', self.form)
        self.assertIn('renderDays();', self.form)

    def test_equipment_and_staff_ids_are_strings(self):
        self.assertIn('day.equipment_ids.map(String)', self.form)
        self.assertIn('String(shift.employee_id)', self.form)

    def test_cancel_releases_lease(self):
        self.assertIn('id="ec_cancel_edit"', self.form)
        self.assertIn('release.append("action", "release")', self.form)

    def test_add_event_still_uses_create_endpoint(self):
        self.assertIn("url_for('save_peachpos_event')", self.form)
        self.assertIn('if (isEditMode) return;', self.form)

if __name__ == "__main__":
    unittest.main()
