import unittest
from pathlib import Path

from jinja2 import Environment


class PeachWebTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "templates/master_admin_website_peachweb.html"
        ).read_text(encoding="utf-8")

        cls.navigation = Path(
            "templates/master_admin_website_management.html"
        ).read_text(encoding="utf-8")

    def test_template_has_valid_jinja_syntax(self):
        Environment().parse(self.source)

    def test_navigation_has_valid_jinja_syntax(self):
        Environment().parse(self.navigation)

    def test_navigation_links_to_peachweb_editor(self):
        self.assertIn(
            "url_for('master_admin_website_peachweb_editor')",
            self.navigation,
        )

    def test_preview_uses_validated_image_reference(self):
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

    def test_caption_appears_below_picture(self):
        image_position = self.source.index(
            'src="{{ showcase.image_url }}"'
        )
        caption_position = self.source.index(
            "<figcaption"
        )
        self.assertLess(
            image_position,
            caption_position,
        )
        self.assertIn(
            "white-space: pre-line",
            self.source,
        )

    def test_image_and_caption_fields_exist(self):
        for name in (
            'name="showcase_image"',
            'name="image_alt"',
            'name="caption"',
        ):
            self.assertIn(name, self.source)

    def test_unimplemented_actions_are_disabled(self):
        self.assertNotIn("<form", self.source)
        self.assertNotIn(
            'method="POST"',
            self.source,
        )
        self.assertNotIn(
            "upload_showcase_image(",
            self.source,
        )
        self.assertIn(
            "Save Draft — Coming Next",
            self.source,
        )
        self.assertGreaterEqual(
            self.source.count("disabled"),
            4,
        )
        self.assertNotIn(
            "|safe",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
