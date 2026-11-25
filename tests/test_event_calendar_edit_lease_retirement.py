"""EC-062-14F-2B: ensure all live Edit Event code is lease independent."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "services/event_calendar_edit_update.py").read_text()
APP = (ROOT / "app.py").read_text()
FORM = (ROOT / "templates/event_new.html").read_text()
CALENDAR = (ROOT / "templates/event_calendar_month.html").read_text()
SERVICE_TREE = ast.parse(SERVICE)
APP_TREE = ast.parse(APP)


class NoEditingLeaseServiceTests(unittest.TestCase):
    def test_old_lease_service_module_is_retired(self):
        self.assertFalse((ROOT / "services/event_calendar_edit_locks.py").exists())

    def test_deprecated_edit_endpoints_absent(self):
        names = {n.name for n in APP_TREE.body if isinstance(n, ast.FunctionDef)}
        for name in ("peachpos_event_edit_lock", "peachpos_event_edit_data",
                     "peachpos_event_edit_save"):
            self.assertNotIn(name, names)

    def test_lease_tokens_are_not_used_by_transaction_coordinator(self):
        self.assertNotIn("lock_token", SERVICE)
        self.assertNotIn("event_calendar_edit_locks", SERVICE)
        self.assertNotIn("require_event_edit_lock_for_save", SERVICE)

    def test_edit_save_uses_scoped_database_row_lock(self):
        self.assertIn("SELECT event_revision FROM public.event_calendar_events", SERVICE)
        self.assertIn("FOR UPDATE", SERVICE)
        self.assertIn("business_unit_id = %s", SERVICE)

    def test_optimistic_revision_check_retained(self):
        self.assertIn("if int(row[0]) != expected_revision", SERVICE)
        self.assertIn("AND event_revision = %s", SERVICE)

    def test_transactional_audit_and_rollback_preserved(self):
        self.assertIn("_append_event_edit_history(", SERVICE)
        self.assertIn("conn.commit()", SERVICE)
        self.assertIn("conn.rollback()", SERVICE)

    def test_browser_does_not_use_leases(self):
        for source in (FORM, CALENDAR):
            self.assertNotIn("edit-lock", source)
            self.assertNotIn("lock_token", source)
            self.assertNotIn("psp:peachpos:event-edit:", source)

    def test_new_endpoints_are_preserved(self):
        names = {n.name for n in APP_TREE.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("peachpos_event_edit_draft", names)
        self.assertIn("peachpos_event_edit_save_unlocked", names)


if __name__ == "__main__":
    unittest.main()
