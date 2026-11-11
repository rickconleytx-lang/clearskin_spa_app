"""EC-062-14C-1: no-lease optimistic save coordinator contracts.

These tests use a fake cursor; a later step will test actual concurrent
PostgreSQL transactions on a disposable local database clone.
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from services.event_calendar_edit_update import (
    EventEditUpdateConflict,
    _lock_current_event_revision,
    update_event_draft,
)


class FakeCursor:
    def __init__(self, revision=1):
        self.revision = revision
        self.row = None
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT event_revision FROM public.event_calendar_events" in sql:
            self.row = ((self.revision,) if self.revision is not None else None)
        elif "SELECT timezone_name FROM public.spas" in sql:
            self.row = ("America/Chicago",)
        else:
            raise AssertionError("Unexpected SQL in no-lease save test: " + sql[:120])

    def fetchone(self):
        return self.row


class FakeConnection:
    autocommit = False

    def __init__(self, revision=1):
        self.cur = FakeCursor(revision)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


SCOPE = dict(spa_id=44, workspace_id=41, event_id=12, expected_revision=1)


class RevisionRowGuardTests(unittest.TestCase):
    def test_current_revision_is_accepted_and_row_locked(self):
        cur = FakeCursor(revision=1)
        self.assertEqual(_lock_current_event_revision(cur, **SCOPE), 1)
        self.assertEqual(len(cur.calls), 1)
        sql, params = cur.calls[0]
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("event_revision", sql)
        self.assertEqual(params, (44, 41, 12))
        for fragment in ("spa_id = %s", "business_unit_id = %s", "event_id = %s"):
            self.assertIn(fragment, sql)
        self.assertNotIn("edit_locks", sql)

    def test_newer_revision_rejected_without_write(self):
        cur = FakeCursor(revision=2)
        with self.assertRaisesRegex(EventEditUpdateConflict, "has changed"):
            _lock_current_event_revision(cur, **SCOPE)
        self.assertEqual(len(cur.calls), 1)

    def test_missing_scoped_event_rejected(self):
        with self.assertRaisesRegex(EventEditUpdateConflict, "no longer available"):
            _lock_current_event_revision(FakeCursor(revision=None), **SCOPE)

    def test_invalid_scope_fails_before_database(self):
        cur = FakeCursor()
        with self.assertRaises(ValueError):
            _lock_current_event_revision(cur, **{**SCOPE, "workspace_id": True})
        self.assertFalse(cur.calls)


class NoLeaseCoordinatorTests(unittest.TestCase):
    def _execute(self, conn, *, override_revision=1):
        target = "services.event_calendar_edit_update."
        before = {"event_revision": 1, "event": {"name": "Before"},
                  "days": [], "custom_values": {}, "custom_labels": {}}
        after = {"event_revision": 2, "event": {"name": "After"},
                 "days": [], "custom_values": {}, "custom_labels": {}}
        order = []
        with ExitStack() as stack:
            stack.enter_context(patch(target + "load_event_edit_payload", side_effect=[before, after]))
            stack.enter_context(patch(target + "validate_event_payload", return_value={
                "event": {"status": "scheduled"}}))
            for name in ("validate_event_resource_ownership",
                         "validate_existing_event_availability",
                         "_delete_old_event_dependents"):
                stack.enter_context(patch(target + name))
            stack.enter_context(patch(target + "_update_existing_event_header", return_value=2))
            stack.enter_context(patch(target + "_create_schedules", return_value={"operating_days": 1}))
            stack.enter_context(patch(target + "_create_custom_values", return_value=0))
            history = stack.enter_context(patch(target + "_append_event_edit_history", return_value=33))
            lease = stack.enter_context(patch(target + "require_event_edit_lock_for_save"))
            result = update_event_draft(
                conn, {"event": {}},
                spa_id=44, workspace_id=41, event_id=12,
                actor_id=34, actor_display_name="Jane Administrator",
                expected_revision=override_revision,  # No lock token!
            )
            lease.assert_not_called()
            history.assert_called_once()
            return result

    def test_optimistic_path_preserves_history_and_commits(self):
        conn = FakeConnection(revision=1)
        result = self._execute(conn)
        self.assertEqual(result["event_id"], 12)
        self.assertEqual(result["revision_after"], 2)
        self.assertEqual(result["history_id"], 33)
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))
        self.assertTrue(any("FOR UPDATE" in sql for sql, _ in conn.cur.calls))
        self.assertFalse(any("edit_locks" in sql for sql, _ in conn.cur.calls))

    def test_stale_edit_rejected_before_delete_and_history(self):
        conn = FakeConnection(revision=2)
        target = "services.event_calendar_edit_update."
        with patch(target + "load_event_edit_payload") as load, \
             patch(target + "_delete_old_event_dependents") as delete, \
             patch(target + "_append_event_edit_history") as history:
            with self.assertRaisesRegex(EventEditUpdateConflict, "has changed"):
                update_event_draft(
                    conn, {"event": {}}, spa_id=44, workspace_id=41,
                    event_id=12, actor_id=34,
                    actor_display_name="Jane Administrator", expected_revision=1,
                )
            load.assert_not_called()
            delete.assert_not_called()
            history.assert_not_called()
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))


if __name__ == "__main__":
    unittest.main()
