import re
import unittest
from pathlib import Path


SOURCE = Path("app.py").read_text(encoding="utf-8")

ROUTE = SOURCE.split(
    "def public_website_settings():", 1
)[1].split(
    "def complete_public_website_settings_onboarding():", 1
)[0]


class PeachWebEventsAppIntegrationTests(unittest.TestCase):

    def test_service_imported(self):
        self.assertIn(
            "from services.peachweb_events_settings import (",
            SOURCE,
        )

    def test_post_parses_events_settings(self):
        self.assertIn(
            '"events_locations_heading" in request.form',
            ROUTE,
        )
        self.assertIn(
            "parse_event_settings_form(",
            ROUTE,
        )

    def test_older_forms_preserve_existing_values(self):
        self.assertEqual(
            ROUTE.count("load_event_settings("),
            2,
        )
        self.assertIn(
            "settings.update(event_settings)",
            ROUTE,
        )

    def test_save_is_inside_normal_transaction(self):
        commits = [
            m.start()
            for m in re.finditer(
                r"conn\.commit\(\)", ROUTE
            )
        ]

        self.assertEqual(len(commits), 2)

        save_position = ROUTE.index("save_event_settings(")

        self.assertLess(commits[0], save_position)
        self.assertLess(save_position, commits[1])

    def test_save_uses_business_workspace_identity(self):
        section = ROUTE.split(
            "save_event_settings(", 1
        )[1].split(")", 1)[0]

        self.assertIn("spa_id=spa_id", section)
        self.assertIn(
            "business_unit_id=business_unit_id",
            section,
        )

    def test_get_loads_events_settings(self):
        section = ROUTE.split(
            'style_row[0] if style_row else "general"', 1
        )[1].split(
            "website_name_row = cur.fetchone()", 1
        )[0]

        self.assertIn(
            "load_event_settings(", section
        )

    def test_route_permission_remains(self):
        prefix = SOURCE.split(
            "def public_website_settings():", 1
        )[0][-300:]

        self.assertIn(
            "can_manage_public_website",
            prefix,
        )


if __name__ == "__main__":
    unittest.main()
