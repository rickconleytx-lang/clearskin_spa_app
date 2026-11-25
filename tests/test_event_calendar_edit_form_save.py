"""EC-062-14D-2: lease-free edit form save and stale revision behavior."""
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
        self.assertIn('"/events/" + editEventId + "/edit-save-unlocked"', FORM)
        self.assertIn('editTransport.addEventListener("submit"', FORM)
        self.assertIn("event.preventDefault();", FORM)

    def test_revision_and_payload_without_lease(self):
        self.assertIn('body.append("expected_revision", String(loadedRevision));', FORM)
        self.assertIn('body.append("event_payload", serialized);', FORM)
        self.assertIn('body.append("security_csrf_token", csrfInput.value);', FORM)
        self.assertNotIn('body.append("lock_token"', FORM)

    def test_no_browser_provided_user_business_or_workspace(self):
        self.assertNotIn('body.append("actor_id"', FORM)
        self.assertNotIn('body.append("spa_id"', FORM)
        self.assertNotIn('body.append("workspace_id"', FORM)

    def test_read_uses_protected_no_lease_draft(self):
        self.assertIn('"/events/" + editEventId + "/edit-draft"', FORM)
        self.assertNotIn('"/events/" + editEventId + "/edit-data"', FORM)

    def test_no_lease_or_heartbeat_in_browser(self):
        self.assertNotIn('edit-lock', FORM)
        self.assertNotIn('renewAfterActualEdit', FORM)
        self.assertNotIn('sessionStorage', FORM)

    def test_stale_save_keeps_form_and_blocks_resubmission(self):
        self.assertIn('response.status === 409', FORM)
        self.assertIn('staleRevision = true;', FORM)
        self.assertIn('if (!staleRevision && !saveSucceeded)', FORM)
        self.assertIn('"Your changes have NOT been saved and remain on "', FORM)

    def test_save_success_checks_revision_and_navigates(self):
        self.assertIn('result.event_revision !== loadedRevision + 1', FORM)
        self.assertIn('saveSucceeded = true;', FORM)
        self.assertIn('window.location.assign("/events/calendar")', FORM)


if __name__ == "__main__":
    unittest.main()
