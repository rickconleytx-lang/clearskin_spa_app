"""Public Packages/Pricing promotional rendering tests.

Renders Jinja templates without Flask, HTTP, or PostgreSQL.
"""

import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined


FILES = {
    "packages": Path(
        "templates/public_site/psp_packages.html"
    ),
    "pricing": Path(
        "templates/public_site/psp_pricing.html"
    ),
}


def promotional_source(page):
    source = FILES[page].read_text()

    marker = '<div role="note" style="'

    if source.count(marker) != 1:
        raise AssertionError(
            "Unexpected promotional box count"
        )

    start = source.index(marker)
    end = source.index("</div>", start) + len("</div>")

    return source[start:end]


class PublicIntroductionTemplateTests(unittest.TestCase):

    def setUp(self):
        self.env = Environment(
            autoescape=True,
            undefined=StrictUndefined,
        )

    def render(self, page, intro=None, include_context=True):
        template = self.env.from_string(
            promotional_source(page)
        )

        if not include_context:
            return template.render()

        return template.render(cms_intro=intro)

    @staticmethod
    def published(
        heading="Published Promotion",
        paragraph="Published promotional details.",
    ):
        return {
            "heading": heading,
            "paragraph": paragraph,
        }

    def test_packages_template_compiles(self):
        self.env.parse(FILES["packages"].read_text())

    def test_pricing_template_compiles(self):
        self.env.parse(FILES["pricing"].read_text())

    def test_packages_static_fallback(self):
        output = self.render("packages")

        self.assertIn("Launch Special", output)
        self.assertIn("<strong>LAUNCH10</strong>", output)

    def test_pricing_static_fallback(self):
        output = self.render("pricing")

        self.assertIn("Launch Special", output)
        self.assertIn("10-day free trial", output)

    def test_missing_context_uses_fallback(self):
        output = self.render(
            "packages",
            include_context=False,
        )
        self.assertIn("Launch Special", output)

    def test_packages_published_heading(self):
        output = self.render(
            "packages",
            self.published("New Packages Heading"),
        )
        self.assertIn("New Packages Heading", output)

    def test_pricing_published_heading(self):
        output = self.render(
            "pricing",
            self.published("New Pricing Heading"),
        )
        self.assertIn("New Pricing Heading", output)

    def test_packages_published_paragraph(self):
        output = self.render(
            "packages",
            self.published(paragraph="New Packages Details"),
        )
        self.assertIn("New Packages Details", output)

    def test_pricing_published_paragraph(self):
        output = self.render(
            "pricing",
            self.published(paragraph="New Pricing Details"),
        )
        self.assertIn("New Pricing Details", output)

    def test_published_hides_static_heading(self):
        output = self.render(
            "packages",
            self.published(),
        )
        self.assertNotIn(
            "Launch Special — Save 10%",
            output,
        )

    def test_published_hides_static_paragraph(self):
        output = self.render(
            "pricing",
            self.published(),
        )
        self.assertNotIn(
            "Enter the code in the discount field",
            output,
        )

    def test_promo_code_remains_bold(self):
        output = self.render(
            "packages",
            self.published(
                paragraph="Use LAUNCH10 when subscribing."
            ),
        )
        self.assertIn(
            "Use <strong>LAUNCH10</strong> when",
            output,
        )

    def test_multiple_codes_are_bold(self):
        output = self.render(
            "pricing",
            self.published(
                paragraph="LAUNCH10 or LAUNCH10"
            ),
        )
        self.assertEqual(
            output.count("<strong>LAUNCH10</strong>"),
            2,
        )

    def test_no_promo_code_adds_no_bold_token(self):
        output = self.render(
            "packages",
            self.published(paragraph="No code mentioned."),
        )
        self.assertNotIn(
            "<strong>LAUNCH10</strong>",
            output,
        )

    def test_heading_escapes_html(self):
        output = self.render(
            "packages",
            self.published(
                heading="<script>alert(1)</script>"
            ),
        )
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

    def test_paragraph_escapes_html(self):
        output = self.render(
            "pricing",
            self.published(
                paragraph="<img src=x onerror=alert(1)>"
            ),
        )
        self.assertNotIn("<img", output)
        self.assertIn("&lt;img", output)

    def test_multiline_paragraph_preserved(self):
        output = self.render(
            "packages",
            self.published(
                paragraph="First line.\\nSecond line."
            ),
        )
        self.assertIn(
            "white-space: pre-line;",
            output,
        )
        self.assertIn(
            "First line.\\nSecond line.",
            output,
        )

    def test_peach_box_style_unchanged(self):
        for page in FILES:
            with self.subTest(page=page):
                source = promotional_source(page)
                self.assertIn(
                    "background: #fff5ef;",
                    source,
                )
                self.assertIn(
                    "border: 1px solid #e9c3ae;",
                    source,
                )
                self.assertIn(
                    "border-radius: 14px;",
                    source,
                )
                self.assertIn(
                    'style="margin:0;"',
                    source,
                )

    def test_other_public_sections_preserved(self):
        packages = FILES["packages"].read_text()
        pricing = FILES["pricing"].read_text()

        self.assertIn(
            "Additional Services &amp; Launch Benefits",
            packages,
        )
        self.assertIn(
            "Simple pricing. Powerful business tools.",
            pricing,
        )
        self.assertIn(
            "Peach Suite Pro Pricing",
            pricing,
        )

    def test_cms_text_never_marked_safe(self):
        for page in FILES:
            with self.subTest(page=page):
                source = promotional_source(page)

                self.assertNotIn("|safe", source)
                self.assertNotIn("| safe", source)
                self.assertNotIn("Markup(", source)


if __name__ == "__main__":
    unittest.main()
