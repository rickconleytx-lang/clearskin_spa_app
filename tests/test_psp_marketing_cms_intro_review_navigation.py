"""Introduction editor review-navigation tests."""

import unittest
from pathlib import Path

from jinja2 import (
    DictLoader,
    Environment,
    StrictUndefined,
    select_autoescape,
)


class IntroductionReviewNavigationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "templates/master_admin_website_intro.html"
        ).read_text()

        cls.env = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "editor.html": cls.source,
            }),
            autoescape=select_autoescape(
                enabled_extensions=("html",),
                default=True,
            ),
            undefined=StrictUndefined,
        )

    def render(self, surface="packages", draft_id=9):
        return self.env.get_template("editor.html").render(
            surface=surface,
            page_label=(
                "Subscription Packages"
                if surface == "packages"
                else "Pricing"
            ),
            content_source="saved draft",
            draft_revision_id=draft_id,
            security_csrf_token="test-csrf",
            intro={
                "heading": "Launch Special",
                "paragraph": "Promotional paragraph.",
            },
            url_for=lambda endpoint, **params: (
                "/test/"
                + endpoint
                + "/"
                + params.get("surface", "")
            ),
        )

    def test_template_compiles(self):
        self.env.parse(self.source)

    def test_packages_saved_draft_shows_review_link(self):
        rendered = self.render()

        self.assertIn(
            "Review Before Publishing",
            rendered,
        )
        self.assertIn(
            "/test/master_admin_website_intro_publish_review/packages",
            rendered,
        )

    def test_pricing_saved_draft_shows_review_link(self):
        rendered = self.render(
            surface="pricing",
            draft_id=22,
        )

        self.assertIn(
            "/test/master_admin_website_intro_publish_review/pricing",
            rendered,
        )

    def test_no_saved_draft_hides_review_link(self):
        rendered = self.render(draft_id=None)

        self.assertNotIn(
            "Review Before Publishing",
            rendered,
        )
        self.assertNotIn(
            "/test/master_admin_website_intro_publish_review/",
            rendered,
        )

    def test_review_link_outside_save_form(self):
        rendered = self.render()

        self.assertLess(
            rendered.index("</form>"),
            rendered.index("Review Before Publishing"),
        )

    def test_save_draft_action_preserved(self):
        rendered = self.render()

        self.assertIn(
            "/test/master_admin_website_intro_save_draft/packages",
            rendered,
        )
        self.assertIn("Save Draft", rendered)

    def test_existing_revision_field_preserved(self):
        rendered = self.render()

        self.assertIn(
            'name="expected_draft_revision_id"',
            rendered,
        )
        self.assertIn('value="9"', rendered)

    def test_review_instructions_use_saved_content(self):
        rendered = self.render()

        self.assertIn(
            "Review uses your last saved draft.",
            rendered,
        )
        self.assertIn(
            "Save any new edits before reviewing.",
            rendered,
        )

    def test_review_does_not_create_second_form(self):
        rendered = self.render()

        self.assertEqual(rendered.count("<form"), 1)
        self.assertEqual(rendered.count("</form>"), 1)


if __name__ == "__main__":
    unittest.main()
