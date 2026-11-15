"""PeachWeb public Events & Locations template checks."""

import unittest
from pathlib import Path
from jinja2 import Environment


SOURCE = Path(
    "templates/public_site/tenant_home.html"
).read_text(encoding="utf-8")

START = "{# PEACHWEB_EVENTS_PUBLIC_START #}"
END = "{# PEACHWEB_EVENTS_PUBLIC_END #}"

FRAGMENT = SOURCE.split(START, 1)[1].split(
    END, 1
)[0]

ENVIRONMENT = Environment(autoescape=True)


class PeachWebPublicTemplateTests(unittest.TestCase):
    def render_section(self, *, is_pos=True, section=None):
        return ENVIRONMENT.from_string(FRAGMENT).render(
            is_peachpos=is_pos,
            public_events_section=section,
        )

    def sample_section(self):
        return {
            "heading": "Where to Find Us",
            "intro": "Find our food trucks!",
            "weeks": [{
                "heading": "November 16–22",
                "events": [{
                    "name": "Taco Festival",
                    "city": "Keller",
                    "hours": "Fr: 11–8 / Sa: 10–9",
                    "directions_url":
                        "https://www.google.com/maps/search/?api=1",
                }],
            }],
        }

    def test_complete_template_parses(self):
        ENVIRONMENT.parse(SOURCE)

    def test_section_follows_promotion_precedes_about(self):
        self.assertLess(
            SOURCE.index('class="promotion-section"'),
            SOURCE.index(START),
        )
        self.assertLess(
            SOURCE.index(END),
            SOURCE.index('class="section about-section"'),
        )

    def test_peachpos_shows_compact_schedule(self):
        html = self.render_section(
            section=self.sample_section()
        )
        self.assertIn("Where to Find Us", html)
        self.assertIn("November 16", html)
        self.assertIn("Taco Festival", html)
        self.assertIn("Keller", html)
        self.assertIn("Fr: 11", html)
        self.assertEqual(
            html.count('class="peachweb-locations-entry"'),
            1,
        )

    def test_solo_does_not_display_section(self):
        html = self.render_section(
            is_pos=False,
            section=self.sample_section(),
        )
        self.assertNotIn(
            'id="where-to-find-us"', html
        )

    def test_missing_or_empty_schedule_is_hidden(self):
        self.assertNotIn(
            'id="where-to-find-us"',
            self.render_section(section=None),
        )
        section = self.sample_section()
        section["weeks"] = []
        self.assertNotIn(
            'id="where-to-find-us"',
            self.render_section(section=section),
        )

    def test_directions_link_is_optional(self):
        section = self.sample_section()
        html = self.render_section(section=section)
        self.assertIn('rel="noopener noreferrer"', html)

        section["weeks"][0]["events"][0][
            "directions_url"
        ] = None
        html = self.render_section(section=section)
        self.assertNotIn('target="_blank"', html)

    def test_event_content_is_html_escaped(self):
        section = self.sample_section()
        section["weeks"][0]["events"][0][
            "name"
        ] = "<script>alert(1)</script>"

        html = self.render_section(section=section)

        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)


if __name__ == "__main__":
    unittest.main()
