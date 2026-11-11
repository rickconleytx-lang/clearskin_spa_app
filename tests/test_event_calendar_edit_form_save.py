"""EC-062-12C: Edit form save wiring; no browser/database writes."""
import unittest
from pathlib import Path

FORM = Path(__file__).resolve().parents[1].joinpath("templates/event_new.html").read_text()


class EventEditFormSaveContracts(unittest.TestCase):
    def test_preserves_create_event_route(self):
        self.assertIn("url_for('save_peachpos_event')", FORM)
        self.assertIn("if (!isEditMode && transport && saveButton", FORM)

    def test_edit_save_can_only_enable_after_prefill(self):
        self.assertIn("renderDays();\n                // Only install Edit Save", FORM)
        self.assertIn("save.disabled = false;", FORM)

    def test_edit_posts_to_separate_endpoint(self):
        self.assertIn('"/events/" + editEventId + "/edit-save"', FORM)
        self.assertIn('editTransport.addEventListener("submit"', FORM)
        self.assertIn("event.preventDefault();", FORM)

    def test_edit_identity_and_revision_are_bound_to_lock(self):
        self.assertIn('body.append("lock_token", editSession.lock_token);', FORM)
        self.assertIn('body.append("expected_revision", String(editSession.event_revision));', FORM)
        self.assertIn('body.append("event_payload", serialized);', FORM)
        self.assertIn('body.append("security_csrf_token", csrfInput.value);', FORM)

    def test_no_browser_provided_user_business_or_workspace(self):
        self.assertNotIn('body.append("actor_id"', FORM)
        self.assertNotIn('body.append("spa_id"', FORM)
        self.assertNotIn('body.append("workspace_id"', FORM)

    def test_renew_only_on_detected_payload_change(self):
        self.assertIn("if (current === lastObservedPayload) return;", FORM)
        self.assertIn("void renewAfterActualEdit();", FORM)
        self.assertIn('renewalBody.append("action", "renew");', FORM)
        self.assertIn('document.addEventListener("input", watchEditingActivity', FORM)
        self.assertIn('document.addEventListener("change", watchEditingActivity', FORM)

    def test_no_passive_heartbeat(self):
        edit_code = FORM.split('// Only install Edit Save', 1)[1]
        self.assertNotIn('setInterval(', edit_code)
        self.assertIn('if (event.isTrusted === false', edit_code)

    def test_server_failure_keeps_edit_open_for_retry(self):
        self.assertIn('if (!sessionLost && !saveSucceeded)', FORM)
        self.assertIn('save.textContent = "Save Changes";', FORM)

    def test_save_success_consumes_browser_session(self):
        self.assertIn('saveSucceeded = true;', FORM)
        self.assertIn('sessionStorage.removeItem(key)', FORM)
        self.assertIn('window.location.assign("/events/calendar")', FORM)


if __name__ == "__main__":
    unittest.main()
