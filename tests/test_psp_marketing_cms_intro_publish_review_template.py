"""Tests for Packages/Pricing introduction review template."""

import unittest
from pathlib import Path

from jinja2 import (
    DictLoader,
    Environment,
    select_autoescape,
)


class IntroductionReviewTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "templates/master_admin_website_intro_publish_review.html"
        ).read_text()

        cls.environment = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "intro_review.html": cls.source,
            }),
            autoescape=select_autoescape(
                enabled_extensions=("html",),
                default=True,
            ),
        )

    def render(self, **changes):
        context = {
            "surface": "packages",
            "page_label": "Subscription Packages",
            "draft_revision_id": 9,
            "draft_intro": {
                "heading": "Draft heading",
                "paragraph": "Draft paragraph",
            },
            "published_revision_id": None,
            "published_intro": None,
            "security_csrf_token": "csrf-example",
        }

        context.update(changes)

        context["url_for"] = (
            lambda endpoint, **params:
                "/test/" + endpoint
                + "/" + params.get("surface", "")
        )

        return self.environment.get_template(
            "intro_review.html"
        ).render(**context)

    def test_template_compiles(self):
        self.environment.parse(self.source)

    def test_extends_existing_layout(self):
        self.assertIn(
            '{% extends "base.html" %}',
            self.source,
        )

    def test_page_specific_heading(self):
        rendered = self.render(
            surface="pricing",
            page_label="Pricing",
        )
        self.assertIn(
            "Review Pricing Introduction",
            rendered,
        )

    def test_saved_draft_displayed(self):
        rendered = self.render()
        self.assertIn("Draft heading", rendered)
        self.assertIn("Draft paragraph", rendered)
        self.assertIn("Draft Revision ID:", rendered)

    def test_no_publication_fallback(self):
        rendered = self.render()
        self.assertIn(
            "No CMS introduction revision has been published",
            rendered,
        )

    def test_published_content_displayed(self):
        rendered = self.render(
            published_revision_id=7,
            published_intro={
                "heading": "Published heading",
                "paragraph": "Published paragraph",
            },
        )
        self.assertIn("Published heading", rendered)
        self.assertIn("Published paragraph", rendered)
        self.assertIn("Published Revision ID:", rendered)

    def test_publish_action_uses_surface(self):
        rendered = self.render(surface="pricing")
        self.assertIn(
            "/test/master_admin_website_intro_publish_draft/pricing",
            rendered,
        )

    def test_csrf_and_revision_fields(self):
        rendered = self.render(
            published_revision_id=7,
            published_intro={
                "heading": "Existing",
                "paragraph": "Published",
            },
        )
        for value in (
            'name="security_csrf_token"',
            'name="expected_draft_revision_id"',
            'name="expected_published_revision_id"',
            'value="csrf-example"',
            'value="9"',
            'value="7"',
        ):
            self.assertIn(value, rendered)

    def test_explicit_publish_confirmation(self):
        rendered = self.render()
        self.assertIn('name="publish_confirmation"', rendered)
        self.assertIn('pattern="PUBLISH"', rendered)
        self.assertIn("Publish This Revision", rendered)

    def test_already_published_has_no_form(self):
        rendered = self.render(
            published_revision_id=9,
            published_intro={
                "heading": "Same revision",
                "paragraph": "Already published",
            },
        )
        self.assertNotIn("<form", rendered)
        self.assertIn(
            "This draft revision is already published",
            rendered,
        )

    def test_escapes_untrusted_content(self):
        rendered = self.render(
            draft_intro={
                "heading": "<script>alert(1)</script>",
                "paragraph": "<b>Untrusted text</b>",
            },
        )
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<b>Untrusted", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;b&gt;", rendered)

    def test_multiline_paragraph_display(self):
        rendered = self.render(
            draft_intro={
                "heading": "Heading",
                "paragraph": "First line\\nSecond line",
            },
        )
        self.assertIn("white-space: pre-line", rendered)
        self.assertIn("First line", rendered)
        self.assertIn("Second line", rendered)

    def test_back_to_editor_uses_surface(self):
        rendered = self.render(surface="pricing")
        self.assertIn(
            "/test/master_admin_website_intro_editor/pricing",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
