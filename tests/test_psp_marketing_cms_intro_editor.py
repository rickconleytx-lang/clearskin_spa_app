"""Tests for the shared page introduction editor template."""

import unittest
from pathlib import Path
from jinja2 import Environment


TEMPLATE = Path(
    "templates/master_admin_website_intro.html"
)


class IntroductionEditorTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text()

    def test_template_compiles(self):
        Environment().parse(self.source)

    def test_extends_existing_layout(self):
        self.assertIn(
            '{% extends "base.html" %}',
            self.source,
        )

    def test_uses_page_specific_title(self):
        self.assertIn("{{ page_label }}", self.source)

    def test_has_heading_field(self):
        self.assertIn('name="heading"', self.source)
        self.assertIn("{{ intro.heading }}", self.source)

    def test_has_paragraph_field(self):
        self.assertIn('name="paragraph"', self.source)
        self.assertIn("{{ intro.paragraph }}", self.source)

    def test_matches_validation_limits(self):
        self.assertIn('maxlength="200"', self.source)
        self.assertIn('maxlength="1200"', self.source)

    def test_has_csrf_token(self):
        self.assertIn(
            'name="security_csrf_token"',
            self.source,
        )

    def test_has_revision_tracking(self):
        self.assertIn(
            'name="expected_draft_revision_id"',
            self.source,
        )

    def test_routes_to_surface_specific_save(self):
        self.assertIn(
            "'master_admin_website_intro_save_draft'",
            self.source,
        )
        self.assertIn("surface=surface", self.source)

    def test_only_offers_draft_save(self):
        self.assertIn("Save Draft", self.source)
        self.assertNotIn('name="publish"', self.source)

    def test_has_management_navigation(self):
        self.assertIn(
            "master_admin_website_management",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
