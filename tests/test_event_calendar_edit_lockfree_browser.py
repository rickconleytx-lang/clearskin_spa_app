"""EC-062-14D-2: behavioral source contracts for browser cutover."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL = (ROOT / 'templates/event_calendar_month.html').read_text()
FORM = (ROOT / 'templates/event_new.html').read_text()


class LockFreeBrowserTests(unittest.TestCase):
    def test_scoped_details_enable_edit_without_lease_url(self):
        # Regression: removing data-edit-lock-url must not hide Edit Event.
        block = CAL.split('renderDetails(payload.event);', 1)[1]
        block = block.split('editButton.addEventListener', 1)[0]
        self.assertIn('Number.isSafeInteger(eventId) && eventId > 0)', block)
        self.assertIn('activeEventButton = button;', block)
        self.assertIn('activeEventId = eventId;', block)
        self.assertIn('editButton.hidden = false;', block)
        self.assertNotIn('button.dataset.editLockUrl', CAL)
        self.assertNotIn('data-edit-lock-url=', CAL)

    def test_open_event_cannot_acquire_lock(self):
        block = CAL.split('editButton.addEventListener("click", function () {', 1)[1]
        block = block.split('closeButton.addEventListener', 1)[0]
        self.assertNotIn('fetch(', block)
        self.assertIn('editUrl.searchParams.set("edit"', block)

    def test_edit_page_does_not_use_session_storage(self):
        self.assertNotIn('sessionStorage', FORM)
        self.assertNotIn('editSession', FORM)

    def test_both_save_and_read_have_csrf(self):
        self.assertGreaterEqual(FORM.count('body.append("security_csrf_token", csrfInput.value)'), 2)

    def test_revision_loaded_from_protected_draft(self):
        self.assertIn('const loadedRevision = draft.event_revision;', FORM)
        self.assertIn('Number.isSafeInteger(draft.event_revision)', FORM)

    def test_save_transmits_only_original_revision(self):
        self.assertIn('body.append("expected_revision", String(loadedRevision));', FORM)
        self.assertNotIn('body.append("lock_token"', FORM)

    def test_non_revision_save_failure_can_be_retried(self):
        self.assertIn('if (!staleRevision && !saveSucceeded)', FORM)
        self.assertIn('save.disabled = false;', FORM)

    def test_stale_revision_preserves_visible_edits(self):
        block = FORM.split('response.status === 409', 1)[1].split('if (!response.ok', 1)[0]
        self.assertIn('staleRevision = true;', block)
        self.assertIn('save.textContent = "Event Changed — Save Blocked";', block)
        self.assertNotIn('window.location.', block)
        self.assertNotIn('window.location.reload', block)

    def test_cannot_double_submit(self):
        self.assertIn('if (saveInProgress || saveSucceeded || staleRevision) return;', FORM)
        self.assertIn('save.disabled = true;', FORM)

    def test_edit_history_kept(self):
        self.assertIn('historyTop.textContent = savedEvent.history_text;', FORM)

    def test_create_workflow_unchanged(self):
        self.assertIn('if (!isEditMode && transport && saveButton', FORM)
        self.assertIn("url_for('save_peachpos_event')", FORM)


if __name__ == '__main__':
    unittest.main()
