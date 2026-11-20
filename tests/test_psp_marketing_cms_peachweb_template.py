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

    def test_save_form_connects_to_private_route(self):
        self.assertIn('method="POST"', self.source)
        self.assertIn(
            "url_for('master_admin_website_peachweb_save_draft')",
            self.source,
        )
        self.assertIn(
            'name="security_csrf_token"',
            self.source,
        )
        self.assertIn(
            'name="expected_draft_revision_id"',
            self.source,
        )

    def test_caption_and_save_button_are_enabled(self):
        import re

        caption = re.search(
            r'<textarea\b[^>]*name="caption"[^>]*>',
            self.source,
            re.S,
        )
        self.assertIsNotNone(caption)
        self.assertNotIn("disabled", caption.group(0))

        button = re.search(
            r'<button\b[^>]*type="submit"[^>]*>',
            self.source,
            re.S,
        )
        self.assertIsNotNone(button)
        self.assertNotIn("disabled", button.group(0))
        self.assertIn("Save Draft", self.source)

    def test_upload_form_uses_multipart_encoding(self):
        self.assertIn(
            'enctype="multipart/form-data"',
            self.source,
        )
        self.assertIn(
            "url_for('master_admin_website_peachweb_save_draft')",
            self.source,
        )
        self.assertIn(
            'name="security_csrf_token"',
            self.source,
        )
        self.assertIn(
            'name="expected_draft_revision_id"',
            self.source,
        )

    def test_picture_and_description_controls_enabled(self):
        import re

        for field in ("showcase_image", "image_alt"):
            matches = re.findall(
                rf'<input\b[^>]*name="{field}"[^>]*>',
                self.source,
                re.S,
            )
            self.assertEqual(len(matches), 1)
            self.assertNotIn("disabled", matches[0])

        self.assertIn(
            'accept="image/jpeg,image/png"',
            self.source,
        )
        self.assertIn("up to 5 MB", self.source)
        self.assertIn(
            'maxlength="180"',
            self.source,
        )

    def test_browser_cannot_supply_image_references(self):
        self.assertNotIn(
            'name="image_public_id"',
            self.source,
        )
        self.assertNotIn(
            'name="image_url"',
            self.source,
        )
        self.assertNotIn("|safe", self.source)
        self.assertEqual(
            self.source.count('type="submit"'),
            1,
        )


if __name__ == "__main__":
    unittest.main()
