import unittest
from pathlib import Path

from jinja2 import DictLoader, Environment


class MarketingCMSPromotionTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.editor = Path(
            "templates/master_admin_website_promotion.html"
        ).read_text(encoding="utf-8")

        cls.management = Path(
            "templates/master_admin_website_management.html"
        ).read_text(encoding="utf-8")

        cls.environment = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "promotion.html": cls.editor,
            }),
            autoescape=True,
        )

    def render_editor(self, **overrides):
        promotion = {
            "product_label": "Solo",
            "headline": (
                "One business.\n"
                "One owner.\n"
                "One connected system."
            ),
            "monthly_price": "$49",
            "pricing_description": (
                "Or $490/year. Start with a 10-day free trial."
            ),
            "features": [
                f"Feature {index}"
                for index in range(1, 10)
            ],
        }

        promotion.update(overrides)

        urls = {
            "master_admin_website_management":
                "/master-admin/website",
            "master_admin_website_promotion_save_draft":
                "/master-admin/website/home/promotion/save",
        }

        return self.environment.get_template(
            "promotion.html"
        ).render(
            promotion=promotion,
            content_source="saved draft",
            draft_revision_id=501,
            security_csrf_token="test-token",
            url_for=lambda endpoint: urls[endpoint],
        )

    def test_protected_save_form(self):
        html = self.render_editor()

        self.assertEqual(html.count("<form"), 1)
        self.assertEqual(html.count("</form>"), 1)
        self.assertIn(
            "/master-admin/website/home/promotion/save",
            html,
        )
        self.assertIn('name="security_csrf_token"', html)
        self.assertIn('value="test-token"', html)

    def test_independent_revision_field(self):
        html = self.render_editor()

        self.assertIn(
            'name="expected_draft_revision_id"',
            html,
        )
        self.assertIn('value="501"', html)

    def test_multiline_headline_is_preserved(self):
        html = self.render_editor()

        self.assertIn(
            "One business.\nOne owner.\n"
            "One connected system.",
            html,
        )
        self.assertIn('name="headline"', html)
        self.assertIn('rows="5"', html)

    def test_all_nine_features_are_editable(self):
        html = self.render_editor()

        self.assertEqual(
            html.count('name="feature_'), 9
        )

        for index in range(1, 10):
            self.assertIn(
                f'name="feature_{index}"',
                html,
            )

    def test_values_are_html_escaped(self):
        html = self.render_editor(
            headline="<script>alert(1)</script>\nHello",
            product_label='Solo "Test"',
        )

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Solo &#34;Test&#34;", html)
        self.assertIn("\nHello", html)

    def test_management_link_preserves_existing_form(self):
        self.assertIn(
            "url_for('master_admin_website_promotion_editor')",
            self.management,
        )
        self.assertEqual(
            self.management.count("<form"), 1
        )
        self.assertEqual(
            self.management.count("</form>"), 1
        )
        self.assertEqual(
            self.management.count('type="submit"'), 1
        )


if __name__ == "__main__":
    unittest.main()
