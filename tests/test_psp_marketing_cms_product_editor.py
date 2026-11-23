"""Isolated product editor form and route-contract tests."""

import ast
import unittest
from pathlib import Path

from services.psp_marketing_cms_content import MarketingContentError
from services.psp_marketing_cms_product_form import (
    blank_product_content,
    format_feature_headings,
    parse_product_form,
)

ROOT = Path(__file__).resolve().parents[1]


def valid_form():
    form = {
        "shared__status": "available",
        "shared__bubble_text": "Available Now",
        "shared__name": "🍑 Solo",
        "shared__monthly_price": "$49",
        "shared__monthly_unit": "/month",
        "shared__annual_price": "$490",
        "shared__annual_unit": "/year",
        "features_text": "PeachBook\nCoach Peach",
        "packages__top_statement_1": "Packages description.",
        "packages__top_statement_2": "",
        "packages__button_text": "Start Free Trial",
        "packages__bottom_heading": "",
        "packages__bottom_statement": "",
        "packages_feature_headings_text": "1 | Included:",
        "pricing__top_statement_1": "Pricing description.",
        "pricing__top_statement_2": "",
        "pricing__button_text": "Start Free Trial",
        "pricing__bottom_heading": "",
        "pricing__bottom_statement": "",
    }
    return form


class ProductEditorFormTests(unittest.TestCase):

    def test_valid_shared_and_page_content(self):
        result = parse_product_form(valid_form())
        self.assertEqual(result["shared"]["monthly_price"], "$49")
        self.assertEqual(
            result["packages"]["top_statement_1"],
            "Packages description.",
        )
        self.assertEqual(
            result["pricing"]["top_statement_1"],
            "Pricing description.",
        )

    def test_ordered_features(self):
        result = parse_product_form(valid_form())
        self.assertEqual(
            result["shared"]["features"],
            ["PeachBook", "Coach Peach"],
        )

    def test_feature_heading_uses_one_based_position(self):
        result = parse_product_form(valid_form())
        self.assertEqual(
            result["packages"]["feature_headings"],
            [{"before_feature": 0, "text": "Included:"}],
        )

    def test_heading_roundtrip(self):
        headings = [{"before_feature": 0, "text": "Included:"}]
        self.assertEqual(
            format_feature_headings(headings),
            "1 | Included:",
        )

    def test_malformed_heading_rejected(self):
        form = valid_form()
        form["packages_feature_headings_text"] = "Wrong format"
        with self.assertRaises(MarketingContentError):
            parse_product_form(form)

    def test_out_of_range_heading_rejected(self):
        form = valid_form()
        form["packages_feature_headings_text"] = "99 | Invalid"
        with self.assertRaises(MarketingContentError):
            parse_product_form(form)

    def test_html_rejected(self):
        form = valid_form()
        form["shared__name"] = "<script>bad</script>"
        with self.assertRaises(MarketingContentError):
            parse_product_form(form)

    def test_missing_price_rejected(self):
        form = valid_form()
        form["shared__annual_price"] = ""
        with self.assertRaises(MarketingContentError):
            parse_product_form(form)

    def test_blank_snapshot_not_valid_to_save(self):
        snapshot = blank_product_content("🍑 Solo", "available")
        self.assertEqual(snapshot["shared"]["annual_price"], "")
        self.assertEqual(snapshot["packages"]["button_text"], "")

    def test_template_jinja_syntax(self):
        from jinja2 import Environment
        source = (
            ROOT / "templates/master_admin_website_product.html"
        ).read_text()
        Environment().parse(source)
        self.assertIn("Stripe price reminder", source)
        self.assertIn("Save Private Draft", source)

    def test_routes_are_master_admin_protected(self):
        tree = ast.parse((ROOT / "app.py").read_text())
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        for name in (
            "master_admin_website_product_editor",
            "master_admin_website_product_save_draft",
        ):
            node = functions[name]
            decorators = [
                ast.unparse(decorator)
                for decorator in node.decorator_list
            ]
            self.assertIn("login_required", decorators)
            self.assertIn("master_admin_required", decorators)
            self.assertTrue(any(
                item.startswith("app.route(")
                for item in decorators
            ))


if __name__ == "__main__":
    unittest.main()
