"""Offline unit tests for PeachPOS exclusive editing leases."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from services.event_calendar_edit_locks import (
    EventEditLockConflict,
    EventEditLockError,
    acquire_event_edit_lock,
    renew_event_edit_lock,
    release_event_edit_lock,
    require_event_edit_lock_for_save,
)


TOKEN = str(uuid.uuid4())
NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
EXPIRY = NOW + timedelta(minutes=15)

SCOPE = dict(
    spa_id=44,
    workspace_id=41,
    event_id=12,
    actor_id=1,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        if not self.rows:
            raise AssertionError("Unexpected fetchone")
        return self.rows.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    autocommit = False

    def __init__(self, rows):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class EventEditingLockTests(unittest.TestCase):

    def test_acquire_new_session(self):
        conn = FakeConnection([
            (1,),
            (TOKEN, 1, EXPIRY),
        ])

        result = acquire_event_edit_lock(conn, **SCOPE)

        self.assertEqual(result["status"], "acquired")
        self.assertEqual(result["event_revision"], 1)
        self.assertEqual(result["lock_token"], TOKEN)
        self.assertEqual(len(conn.cur.statements), 2)

    def test_missing_event_does_not_create_lock(self):
        conn = FakeConnection([None])

        result = acquire_event_edit_lock(conn, **SCOPE)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(len(conn.cur.statements), 1)

    def test_busy_lock_displays_editor_name(self):
        conn = FakeConnection([
            (1,),
            None,
            ("Jane Administrator", EXPIRY),
        ])

        result = acquire_event_edit_lock(conn, **SCOPE)

        self.assertEqual(result["status"], "busy")
        self.assertEqual(
            result["editor_display_name"],
            "Jane Administrator",
        )
        self.assertNotIn("email", result)

    def test_second_tab_cannot_replace_active_lock(self):
        conn = FakeConnection([
            (1,),
            None,
            ("Current Editor", EXPIRY),
        ])

        result = acquire_event_edit_lock(conn, **SCOPE)

        self.assertEqual(result["status"], "busy")
        self.assertNotIn("lock_token", result)

    def test_renew_active_lease(self):
        conn = FakeConnection([(EXPIRY, 1)])

        result = renew_event_edit_lock(
            conn, lock_token=TOKEN, **SCOPE
        )

        self.assertEqual(result["status"], "renewed")
        self.assertEqual(result["event_revision"], 1)

    def test_expired_or_missing_lease_cannot_renew(self):
        conn = FakeConnection([None])

        result = renew_event_edit_lock(
            conn, lock_token=TOKEN, **SCOPE
        )

        self.assertEqual(result["status"], "lost")

    def test_release_owned_session(self):
        conn = FakeConnection([(12,)])

        result = release_event_edit_lock(
            conn, lock_token=TOKEN, **SCOPE
        )

        self.assertTrue(result["released"])

    def test_release_rejects_other_session(self):
        conn = FakeConnection([None])

        result = release_event_edit_lock(
            conn, lock_token=TOKEN, **SCOPE
        )

        self.assertFalse(result["released"])

    def test_save_guard_accepts_current_session(self):
        cur = FakeCursor([
            (1, 1, EXPIRY),
            (NOW,),
        ])

        revision = require_event_edit_lock_for_save(
            cur,
            lock_token=TOKEN,
            expected_revision=1,
            **SCOPE,
        )

        self.assertEqual(revision, 1)

    def test_save_guard_rejects_stale_revision(self):
        cur = FakeCursor([
            (2, 1, EXPIRY),
            (NOW,),
        ])

        with self.assertRaises(EventEditLockConflict):
            require_event_edit_lock_for_save(
                cur,
                lock_token=TOKEN,
                expected_revision=1,
                **SCOPE,
            )

    def test_save_guard_rejects_expired_lease(self):
        cur = FakeCursor([
            (1, 1, NOW),
            (NOW,),
        ])

        with self.assertRaises(EventEditLockConflict):
            require_event_edit_lock_for_save(
                cur,
                lock_token=TOKEN,
                expected_revision=1,
                **SCOPE,
            )

    def test_save_guard_rejects_missing_lock(self):
        cur = FakeCursor([None])

        with self.assertRaises(EventEditLockConflict):
            require_event_edit_lock_for_save(
                cur,
                lock_token=TOKEN,
                expected_revision=1,
                **SCOPE,
            )

    def test_invalid_session_token_rejected(self):
        conn = FakeConnection([])

        with self.assertRaises(EventEditLockError):
            renew_event_edit_lock(
                conn, lock_token="not-a-uuid", **SCOPE
            )

    def test_invalid_scope_rejected(self):
        conn = FakeConnection([])

        with self.assertRaises(EventEditLockError):
            acquire_event_edit_lock(
                conn,
                **{**SCOPE, "event_id": True},
            )

    def test_autocommit_connection_rejected(self):
        conn = FakeConnection([])
        conn.autocommit = True

        with self.assertRaises(EventEditLockError):
            acquire_event_edit_lock(conn, **SCOPE)


if __name__ == "__main__":
    unittest.main()
