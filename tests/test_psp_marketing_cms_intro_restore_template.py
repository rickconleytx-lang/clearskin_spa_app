"""Isolated introduction restoration template tests."""

import copy
import unittest
from pathlib import Path

from jinja2 import (
    DictLoader,
    Environment,
    StrictUndefined,
    select_autoescape,
)


def sample_target():
    return {
        "revision_id": 10,
        "revision_number": 3,
        "created_at": "2026-11-20",
        "was_published": True,
        "is_published": False,
        "intro": {
            "heading": "Earlier Promotion",
            "paragraph": "Earlier details.\nSecond line.",
        },
    }


def sample_current():
    return {
        "revision_id": 13,
        "revision_number": 4,
        "created_at": "2026-11-21",
        "was_published": True,
        "is_published": True,
        "intro": {
            "heading": "Current Promotion",
            "paragraph": "Current details.",
        },
    }


class IntroductionRestoreTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "templates/master_admin_website_intro_restore_review.html"
        ).read_text()

        cls.environment = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "review.html": cls.source,
            }),
            autoescape=select_autoescape(
                enabled_extensions=("html",),
                default=True,
            ),
            undefined=StrictUndefined,
        )

    def render(
        self,
        surface="packages",
        draft_id=15,
        target=None,
        current=None,
    ):
        return self.environment.get_template(
            "review.html"
        ).render(
            surface=surface,
            page_label=(
                "Subscription Packages"
                if surface == "packages"
                else "Pricing"
            ),
            target=copy.deepcopy(
                target if target is not None
                else sample_target()
            ),
            current=copy.deepcopy(
                current if current is not None
                else sample_current()
            ),
            draft_revision_id=draft_id,
            security_csrf_token="TEST-CSRF-TOKEN",
            url_for=lambda endpoint, **kwargs: (
                "/test/" + endpoint +
                "/" + kwargs.get("surface", "")
            ),
        )

    def test_template_compiles(self):
        self.environment.parse(self.source)

    def test_packages_title(self):
        self.assertIn(
            "Review Subscription Packages Introduction Restoration",
            self.render(),
        )

    def test_pricing_title(self):
        self.assertIn(
            "Review Pricing Introduction Restoration",
            self.render(surface="pricing"),
        )

    def test_back_to_packages_history(self):
        self.assertIn(
            "/test/master_admin_website_intro_history/packages",
            self.render(),
        )

    def test_back_to_pricing_history(self):
        self.assertIn(
            "/test/master_admin_website_intro_history/pricing",
            self.render(surface="pricing"),
        )

    def test_target_revision_number_and_id(self):
        output = self.render()

        self.assertIn("Revision to Restore", output)
        self.assertIn("ID 10", output)
        self.assertIn("Earlier Promotion", output)

    def test_current_revision_number_and_id(self):
        output = self.render()

        self.assertIn(
            "Currently Published Introduction",
            output,
        )
        self.assertIn("ID 13", output)
        self.assertIn("Current Promotion", output)

    def test_target_paragraph_displayed(self):
        output = self.render()

        self.assertIn("Earlier details.", output)
        self.assertIn("Second line.", output)
        self.assertIn("white-space: pre-line", output)

    def test_current_paragraph_displayed(self):
        self.assertIn(
            "Current details.",
            self.render(),
        )

    def test_saved_draft_preservation(self):
        output = self.render()

        self.assertIn(
            "Current saved draft:",
            output,
        )
        self.assertIn(
            "Revision ID 15",
            output,
        )
        self.assertIn(
            "draft will be preserved",
            output,
        )

    def test_no_saved_draft(self):
        self.assertIn(
            "No saved draft exists.",
            self.render(draft_id=None),
        )

    def test_packages_post_action(self):
        output = self.render()

        self.assertIn(
            "/test/master_admin_website_intro_restore_revision/packages",
            output,
        )
        self.assertIn('method="POST"', output)

    def test_pricing_post_action(self):
        self.assertIn(
            "/test/master_admin_website_intro_restore_revision/pricing",
            self.render(surface="pricing"),
        )

    def test_csrf_token_field(self):
        output = self.render()

        self.assertIn(
            'name="security_csrf_token"',
            output,
        )
        self.assertIn("TEST-CSRF-TOKEN", output)

    def test_target_revision_hidden_field(self):
        output = self.render()

        self.assertIn(
            'name="revision_id"',
            output,
        )
        self.assertIn('value="10"', output)

    def test_expected_publication_hidden_field(self):
        output = self.render()

        self.assertIn(
            'name="expected_published_revision_id"',
            output,
        )
        self.assertIn('value="13"', output)

    def test_restore_confirmation_is_required(self):
        output = self.render()

        self.assertIn(
            'name="restore_confirmation"',
            output,
        )
        self.assertIn('pattern="RESTORE"', output)
        self.assertIn('maxlength="7"', output)
        self.assertIn(
            "Type RESTORE to confirm",
            output,
        )

    def test_historical_heading_is_escaped(self):
        target = sample_target()
        target["intro"]["heading"] = (
            "<script>alert(1)</script>"
        )

        output = self.render(target=target)

        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

    def test_public_page_status_is_accurate(self):
        output = self.render()

        self.assertIn(
            "Public-page CMS rendering is not yet connected.",
            output,
        )
        self.assertIn(
            "CMS publication",
            output,
        )

    def test_review_requires_separate_confirmation(self):
        output = self.render()

        self.assertIn(
            "Reviewing this screen does not restore anything.",
            output,
        )
        self.assertEqual(
            output.count("<form"),
            1,
        )
        self.assertEqual(
            output.count("</form>"),
            1,
        )
        self.assertNotIn("<textarea", output)


if __name__ == "__main__":
    unittest.main()
