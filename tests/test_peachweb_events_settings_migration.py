import re
import unittest
from pathlib import Path


MIGRATION = Path(
    "migrations/peachweb_events_locations_settings_v1.sql"
)


class PeachWebSettingsMigrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.sql.lower().split())

    def test_only_expected_columns_added(self):
        columns = re.findall(
            r"ADD COLUMN IF NOT EXISTS\s+(\w+)",
            self.sql,
            flags=re.IGNORECASE,
        )

        self.assertEqual(columns, [
            "show_events_locations",
            "events_locations_heading",
            "events_locations_intro",
            "events_locations_show_directions",
            "events_locations_show_daily_hours",
        ])

    def test_master_toggle_defaults_disabled(self):
        self.assertRegex(
            self.normalized,
            r"show_events_locations boolean not null default false",
        )

    def test_display_options_have_safe_defaults(self):
        self.assertIn(
            "events_locations_heading varchar(180) "
            "not null default 'where to find us'",
            self.normalized,
        )
        self.assertIn(
            "events_locations_show_directions "
            "boolean not null default true",
            self.normalized,
        )
        self.assertIn(
            "events_locations_show_daily_hours "
            "boolean not null default true",
            self.normalized,
        )

    def test_migration_only_alters_website_settings(self):
        self.assertEqual(
            re.findall(
                r"ALTER TABLE\s+([\w.]+)",
                self.sql,
                flags=re.IGNORECASE,
            ),
            ["public.public_website_settings"],
        )

        self.assertNotRegex(
            self.sql,
            r"(?im)^\s*(update|delete|insert|drop|truncate)\b",
        )

    def test_transaction_and_whitespace(self):
        self.assertIn("BEGIN;", self.sql)
        self.assertIn("COMMIT;", self.sql)
        self.assertTrue(self.sql.endswith("\n"))

        for line in self.sql.splitlines():
            self.assertEqual(line, line.rstrip())


if __name__ == "__main__":
    unittest.main()
