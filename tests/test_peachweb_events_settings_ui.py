import re
import unittest
from pathlib import Path

from jinja2 import Environment

from services.provisioning_service import (
    PUBLIC_WEBSITE_DEFAULTS,
)


SOURCE = Path(
    "templates/public_website_settings.html"
).read_text(encoding="utf-8")

START = "{# PEACHWEB_EVENTS_SETTINGS_START #}"
END = "{# PEACHWEB_EVENTS_SETTINGS_END #}"

BLOCK = SOURCE.split(START, 1)[1].split(END, 1)[0]


class PeachWebEventsSettingsUITests(unittest.TestCase):

    def render(self, tier, **overrides):
        settings = dict(PUBLIC_WEBSITE_DEFAULTS)
        settings.update(overrides)

        return Environment(autoescape=True).from_string(
            BLOCK
        ).render(
            navigation_subscription_tier_code=tier,
            settings=settings,
        )

    def test_entire_template_parses(self):
        Environment().parse(SOURCE)

    def test_section_position(self):
        self.assertEqual(SOURCE.count(START), 1)
        self.assertEqual(SOURCE.count(END), 1)

        self.assertLess(
            SOURCE.index("<h2>Promotional Section</h2>"),
            SOURCE.index(START),
        )
        self.assertLess(
            SOURCE.index(END),
            SOURCE.index("<h2>Introduction Card</h2>"),
        )
        self.assertLess(
            SOURCE.index(END),
            SOURCE.index("<h2>About Section</h2>"),
        )

    def test_peachpos_sees_controls(self):
        html = self.render("pos")

        self.assertIn("Events &amp; Locations", html)
        self.assertIn(
            'name="show_events_locations"', html
        )
        self.assertIn("Where to Find Us", html)

    def test_solo_and_team_do_not_see_controls(self):
        for tier in ("solo", "team", "", None):
            with self.subTest(tier=tier):
                html = self.render(tier)

                self.assertNotIn(
                    'name="show_events_locations"',
                    html,
                )
                self.assertNotIn(
                    "<h2>Events &amp; Locations</h2>",
                    html,
                )

    def test_each_field_present_once(self):
        for name in (
            "show_events_locations",
            "events_locations_heading",
            "events_locations_intro",
            "events_locations_show_directions",
            "events_locations_show_daily_hours",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    BLOCK.count(f'name="{name}"'), 1
                )

    def test_master_toggle_defaults_off(self):
        html = self.render("pos")

        match = re.search(
            r'<input\b[^>]*id="show_events_locations"[^>]*>',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertNotIn("checked", match.group(0))

        enabled = self.render(
            "pos",
            show_events_locations=True,
        )

        match = re.search(
            r'<input\b[^>]*id="show_events_locations"[^>]*>',
            enabled,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        self.assertIn("checked", match.group(0))

    def test_custom_text_is_escaped(self):
        html = self.render(
            "pos",
            events_locations_heading="Lunch & <Dinner>",
            events_locations_intro="Meet <us>!",
        )

        self.assertIn(
            "Lunch &amp; &lt;Dinner&gt;",
            html,
        )
        self.assertIn(
            "Meet &lt;us&gt;!",
            html,
        )
        self.assertNotIn("Meet <us>!", html)


if __name__ == "__main__":
    unittest.main()
