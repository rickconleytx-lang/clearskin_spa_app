import re
import unittest
from pathlib import Path

from services.provisioning_service import (
    PUBLIC_WEBSITE_DEFAULTS,
    resolve_peachpos_website_defaults,
)


class PeachWebEventsDefaultsTests(unittest.TestCase):

    def test_public_schedule_disabled_by_default(self):
        self.assertIs(
            PUBLIC_WEBSITE_DEFAULTS["show_events_locations"],
            False,
        )

    def test_default_heading_and_introduction(self):
        self.assertEqual(
            PUBLIC_WEBSITE_DEFAULTS["events_locations_heading"],
            "Where to Find Us",
        )
        self.assertEqual(
            PUBLIC_WEBSITE_DEFAULTS["events_locations_intro"],
            "Find our food trucks at these upcoming "
            "events and locations!",
        )

    def test_directions_and_hours_enabled_by_default(self):
        self.assertIs(
            PUBLIC_WEBSITE_DEFAULTS[
                "events_locations_show_directions"
            ],
            True,
        )
        self.assertIs(
            PUBLIC_WEBSITE_DEFAULTS[
                "events_locations_show_daily_hours"
            ],
            True,
        )

    def test_defaults_match_migration_columns(self):
        sql = Path(
            "migrations/"
            "peachweb_events_locations_settings_v1.sql"
        ).read_text(encoding="utf-8")

        columns = re.findall(
            r"ADD COLUMN IF NOT EXISTS\s+(\w+)",
            sql,
            flags=re.IGNORECASE,
        )

        self.assertEqual(
            set(columns),
            {
                "show_events_locations",
                "events_locations_heading",
                "events_locations_intro",
                "events_locations_show_directions",
                "events_locations_show_daily_hours",
            },
        )

        for column in columns:
            self.assertIn(column, PUBLIC_WEBSITE_DEFAULTS)

    def test_peachpos_styles_preserve_event_settings(self):
        for style in ("general", "food", "retail"):
            with self.subTest(style=style):
                settings = PUBLIC_WEBSITE_DEFAULTS.copy()
                settings["show_events_locations"] = True
                settings["events_locations_heading"] = (
                    "Our Weekly Locations"
                )

                original = settings.copy()

                result = resolve_peachpos_website_defaults(
                    settings, style
                )

                self.assertTrue(
                    result["show_events_locations"]
                )
                self.assertEqual(
                    result["events_locations_heading"],
                    "Our Weekly Locations",
                )
                self.assertEqual(settings, original)


if __name__ == "__main__":
    unittest.main()
