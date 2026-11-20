import re
import unittest
from pathlib import Path
from jinja2 import Environment


class PeachBookTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "templates/master_admin_website_peachbook.html"
        ).read_text(encoding="utf-8")

        cls.navigation = Path(
            "templates/master_admin_website_management.html"
        ).read_text(encoding="utf-8")

    def test_valid_jinja_template(self):
        Environment().parse(self.source)

    def test_valid_navigation_template(self):
        Environment().parse(self.navigation)

    def test_navigation_opens_peachbook_editor(self):
        self.assertIn(
            "url_for('master_admin_website_peachbook_editor')",
            self.navigation,
        )

    def test_picture_preview_present(self):
        self.assertIn(
            'src="{{ showcase.image_url }}"',
            self.source,
        )
        self.assertIn(
            'alt="{{ showcase.image_alt }}"',
            self.source,
        )
        self.assertIn(
            "{% if showcase.image_url %}",
            self.source,
        )

    def test_caption_below_picture(self):
        self.assertLess(
            self.source.index('src="{{ showcase.image_url }}"'),
            self.source.index("<figcaption"),
        )
        self.assertIn("white-space: pre-line", self.source)

    def test_controls_present_but_disabled(self):
        for field, element in (
            ("showcase_image", "input"),
            ("image_alt", "input"),
            ("caption", "textarea"),
        ):
            match = re.search(
                rf'<{element}\b[^>]*name="{field}"[^>]*>',
                self.source,
                re.S,
            )
            self.assertIsNotNone(match, field)
            self.assertIn("disabled", match.group(0))

        self.assertIn(
            "Save Draft — Coming Next",
            self.source,
        )

    def test_no_active_save_or_browser_image_references(self):
        self.assertNotIn("<form", self.source)
        self.assertNotIn('method="POST"', self.source)
        self.assertNotIn(
            'name="image_public_id"',
            self.source,
        )
        self.assertNotIn(
            'name="image_url"',
            self.source,
        )
        self.assertNotIn("|safe", self.source)


if __name__ == "__main__":
    unittest.main()
