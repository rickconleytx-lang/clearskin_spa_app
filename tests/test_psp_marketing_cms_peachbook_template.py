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

    def test_showcase_fields_enabled_for_draft_saving(self):
        for field, element, should_be_disabled in (
            ("showcase_image", "input", False),
            ("image_alt", "input", False),
            ("caption", "textarea", False),
        ):
            match = re.search(
                rf'<{element}\b[^>]*name="{field}"[^>]*>',
                self.source,
                re.S,
            )
            self.assertIsNotNone(match, field)
            self.assertEqual(
                bool(re.search(r"\bdisabled\b", match.group(0))),
                should_be_disabled,
                field,
            )

        self.assertIn("Save Draft", self.source)
        self.assertNotIn("Save Draft — Coming Next", self.source)

    def test_protected_form_without_browser_image_references(self):
        self.assertEqual(self.source.count("<form"), 1)
        self.assertEqual(self.source.count("</form>"), 1)
        self.assertIn('method="POST"', self.source)
        self.assertIn('name="security_csrf_token"', self.source)
        self.assertIn('name="expected_draft_revision_id"', self.source)
        self.assertIn(
            "url_for('master_admin_website_peachbook_save_draft')",
            self.source,
        )
        self.assertNotIn('name="image_public_id"', self.source)
        self.assertNotIn('name="image_url"', self.source)
        self.assertNotIn("|safe", self.source)


if __name__ == "__main__":
    unittest.main()
