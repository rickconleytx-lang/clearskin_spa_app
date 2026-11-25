"""Master Admin subscription product navigation tests."""

import ast
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (
    ROOT / "templates/master_admin_website_management.html"
)

START = "<!-- PRODUCT EDITOR NAV START -->"
END = "<!-- PRODUCT EDITOR NAV END -->"

PRODUCTS = {
    "solo": "Solo",
    "peachpos": "PeachPOS",
    "team": "Team",
    "collective": "Peach Collective",
}


def navigation_html():
    source = TEMPLATE.read_text()
    assert source.count(START) == 1
    assert source.count(END) == 1

    fragment = source.split(START, 1)[1].split(END, 1)[0]

    return Environment(autoescape=True).from_string(
        fragment
    ).render(
        url_for=lambda endpoint, **kwargs: (
            "/master-admin/website/products/"
            + kwargs["product_key"]
            if endpoint == "master_admin_website_product_editor"
            else "/unexpected-route"
        )
    )


class ProductNavigationTests(unittest.TestCase):

    def test_four_product_links_render(self):
        html = navigation_html()

        for key, label in PRODUCTS.items():
            with self.subTest(product=key):
                self.assertIn(
                    "/master-admin/website/products/" + key,
                    html,
                )
                self.assertIn("Edit " + label, html)

    def test_exactly_four_product_links(self):
        html = navigation_html()
        self.assertEqual(
            html.count('href="/master-admin/website/products/'),
            4,
        )
        self.assertNotIn("/unexpected-route", html)

    def test_existing_intro_links_preserved(self):
        source = TEMPLATE.read_text()
        self.assertIn(
            "master_admin_website_intro_editor",
            source,
        )
        self.assertIn(
            "surface='packages'",
            source,
        )
        self.assertIn(
            "surface='pricing'",
            source,
        )

    def test_navigation_is_private_editor_only(self):
        html = navigation_html()
        self.assertNotIn("/publish", html)
        self.assertNotIn("/signup/", html)
        self.assertIn(
            "remain private until separately published",
            html,
        )


if __name__ == "__main__":
    unittest.main()
