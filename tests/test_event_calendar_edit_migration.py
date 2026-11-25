import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MIGRATION = (
    ROOT / "migrations/peachpos_event_edit_controls_v1.sql"
)


class EventEditMigrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text()

    def test_event_revision(self):
        self.assertIn(
            "ADD COLUMN event_revision BIGINT NOT NULL DEFAULT 1;",
            self.sql,
        )
        self.assertIn(
            "CHECK (event_revision >= 1)",
            self.sql,
        )

    def test_exclusive_workspace_scoped_lock(self):
        self.assertIn(
            "CREATE TABLE public.event_calendar_edit_locks",
            self.sql,
        )
        self.assertRegex(
            self.sql,
            r"PRIMARY KEY\s*\(\s*spa_id,\s*"
            r"business_unit_id,\s*event_id\s*\)",
        )

    def test_lock_session_and_administrator(self):
        self.assertIn(
            "lock_token UUID NOT NULL UNIQUE",
            self.sql,
        )
        self.assertIn(
            "editor_user_id INTEGER NOT NULL",
            self.sql,
        )

    def test_fifteen_minute_lease_constraint(self):
        self.assertIn(
            "last_activity_at >= acquired_at",
            self.sql,
        )
        self.assertIn(
            "expires_at > last_activity_at",
            self.sql,
        )
        self.assertIn(
            "INTERVAL '15 minutes'",
            self.sql,
        )

    def test_lock_revision_tracking(self):
        self.assertIn(
            "base_revision BIGINT NOT NULL",
            self.sql,
        )
        self.assertIn(
            "CHECK (base_revision >= 1)",
            self.sql,
        )

    def test_lock_references_existing_event(self):
        self.assertIn(
            "CONSTRAINT fk_event_edit_lock_event",
            self.sql,
        )
        self.assertIn(
            "REFERENCES public.event_calendar_events",
            self.sql,
        )

    def test_history_has_workspace_and_actor(self):
        self.assertIn(
            "CREATE TABLE public.event_calendar_edit_history",
            self.sql,
        )
        self.assertIn(
            "CONSTRAINT fk_event_edit_history_event",
            self.sql,
        )
        self.assertIn(
            "actor_user_id INTEGER NOT NULL",
            self.sql,
        )

    def test_history_revision_integrity(self):
        self.assertIn(
            "revision_after = revision_before + 1",
            self.sql,
        )
        self.assertRegex(
            self.sql,
            r"UNIQUE\s*\(\s*spa_id,\s*"
            r"business_unit_id,\s*event_id,\s*"
            r"revision_after\s*\)",
        )

    def test_history_preserves_changes(self):
        self.assertIn(
            "actor_display_name VARCHAR(200) NOT NULL",
            self.sql,
        )
        self.assertIn(
            "changes_json JSONB NOT NULL",
            self.sql,
        )
        self.assertIn(
            "jsonb_typeof(changes_json) = 'object'",
            self.sql,
        )

    def test_history_append_only(self):
        self.assertIn(
            "CREATE FUNCTION public.guard_event_edit_history()",
            self.sql,
        )
        self.assertIn(
            "BEFORE UPDATE OR DELETE",
            self.sql,
        )
        self.assertIn(
            "EXECUTE FUNCTION public.guard_event_edit_history()",
            self.sql,
        )

    def test_history_and_expiration_indexes(self):
        self.assertIn(
            "idx_event_edit_lock_expiration",
            self.sql,
        )
        self.assertIn(
            "idx_event_edit_history_lookup",
            self.sql,
        )

    def test_transaction_and_no_destructive_commands(self):
        self.assertTrue(
            self.sql.strip().startswith("BEGIN;")
        )
        self.assertTrue(
            self.sql.strip().endswith("COMMIT;")
        )
        self.assertIsNone(
            re.search(
                r"(?im)^\s*(DROP|TRUNCATE|DELETE\s+FROM)\b",
                self.sql,
            )
        )


if __name__ == "__main__":
    unittest.main()
