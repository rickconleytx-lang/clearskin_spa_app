"""Read-only editing-session verification tests."""

import unittest
import uuid

from services.event_calendar_edit_locks import (
    EventEditLockConflict,
    EventEditLockError,
    require_event_edit_lock_for_read,
)


TOKEN = str(uuid.uuid4())

SCOPE = dict(
    spa_id=44,
    workspace_id=41,
    event_id=12,
    actor_id=34,
)


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.statements = []

    def execute(self, statement, params):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.row


class EventEditReadGuardTests(unittest.TestCase):

    def verify(self, cursor, **changes):
        return require_event_edit_lock_for_read(
            cursor,
            lock_token=TOKEN,
            **{**SCOPE, **changes},
        )

    def test_valid_session_returns_revision(self):
        cursor = FakeCursor((1, 1, True))

        self.assertEqual(self.verify(cursor), 1)
        self.assertEqual(len(cursor.statements), 1)

    def test_missing_or_wrong_session_rejected(self):
        cursor = FakeCursor(None)

        with self.assertRaises(EventEditLockConflict):
            self.verify(cursor)

    def test_expired_session_rejected(self):
        cursor = FakeCursor((1, 1, False))

        with self.assertRaises(EventEditLockConflict):
            self.verify(cursor)

    def test_stale_event_revision_rejected(self):
        cursor = FakeCursor((2, 1, True))

        with self.assertRaises(EventEditLockConflict):
            self.verify(cursor)

    def test_invalid_session_token_rejected(self):
        cursor = FakeCursor((1, 1, True))

        with self.assertRaises(EventEditLockError):
            require_event_edit_lock_for_read(
                cursor,
                lock_token="not-a-uuid",
                **SCOPE,
            )

        self.assertEqual(cursor.statements, [])

    def test_non_v4_token_rejected(self):
        cursor = FakeCursor((1, 1, True))

        with self.assertRaises(EventEditLockError):
            require_event_edit_lock_for_read(
                cursor,
                lock_token=str(uuid.uuid1()),
                **SCOPE,
            )

        self.assertEqual(cursor.statements, [])

    def test_invalid_scope_rejected(self):
        cursor = FakeCursor((1, 1, True))

        with self.assertRaises(EventEditLockError):
            self.verify(cursor, workspace_id=True)

        self.assertEqual(cursor.statements, [])

    def test_query_is_scoped_and_read_only(self):
        cursor = FakeCursor((1, 1, True))

        self.verify(cursor)

        statement, params = cursor.statements[0]

        self.assertEqual(
            params,
            (44, 41, 12, 34, TOKEN),
        )

        for fragment in (
            "e.spa_id = %s",
            "e.business_unit_id = %s",
            "e.event_id = %s",
            "l.editor_user_id = %s",
            "l.lock_token = %s::uuid",
            "l.expires_at > clock_timestamp()",
        ):
            self.assertIn(fragment, statement)

        self.assertTrue(statement.strip().startswith("SELECT"))

        self.assertNotIn("FOR UPDATE", statement.upper())
        self.assertNotIn("INSERT INTO", statement.upper())
        self.assertNotIn("DELETE FROM", statement.upper())


if __name__ == "__main__":
    unittest.main()
