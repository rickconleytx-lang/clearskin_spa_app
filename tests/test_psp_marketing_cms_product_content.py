"""Product content contract tests."""

import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_product_content import (
    normalize_product_content,
)
from services.psp_marketing_cms_product_features import (
    packages_product_features,
    pricing_product_features,
)


def example_product():
    return {
        "shared": {
            "status": "coming_soon",
            "bubble_text": "Available January 2027",
            "name": "🍑 Peach Collective",
            "monthly_price": "$49",
            "annual_price": "$490",
            "monthly_unit": "/ provider / month",
            "annual_unit": "/ provider / year",
            "features": [
                f"Feature {i}"
                for i in range(1, 16)
            ],
        },
        "packages": {
            "top_statement_1": "Independent providers.",
            "top_statement_2": "Private workspaces.",
            "button_text": "Coming January 2027",
            "bottom_heading": "",
            "bottom_statement": "",
            "feature_headings": [
                {
                    "before_feature": 0,
                    "text": "Each provider receives:",
                },
                {
                    "before_feature": 8,
                    "text": "The group can share:",
                },
            ],
        },
        "pricing": {
            "top_statement_1": "Per-provider pricing.",
            "top_statement_2": "Annual billing available.",
            "button_text": "Coming January 2027",
            "bottom_heading": "",
            "bottom_statement": "",
        },
    }


class ProductContentTests(unittest.TestCase):

    def test_valid_product(self):
        content = normalize_product_content(
            example_product()
        )
        self.assertEqual(
            content["shared"]["status"],
            "coming_soon",
        )

    def test_preserves_per_provider_prices(self):
        content = normalize_product_content(
            example_product()
        )
        self.assertEqual(
            content["shared"]["monthly_unit"],
            "/ provider / month",
        )

    def test_packages_all_features(self):
        content = normalize_product_content(
            example_product()
        )
        self.assertEqual(
            len(packages_product_features(
                content["shared"]["features"]
            )),
            15,
        )

    def test_pricing_first_ten(self):
        content = normalize_product_content(
            example_product()
        )
        self.assertEqual(
            len(pricing_product_features(
                content["shared"]["features"]
            )),
            10,
        )

    def test_preserves_group_headings(self):
        content = normalize_product_content(
            example_product()
        )
        self.assertEqual(
            content["packages"]["feature_headings"][1]
            ["before_feature"],
            8,
        )

    def test_independent_page_content(self):
        content = normalize_product_content(
            example_product()
        )
        self.assertNotEqual(
            content["packages"]["top_statement_1"],
            content["pricing"]["top_statement_1"],
        )

    def test_rejects_unknown_status(self):
        data = example_product()
        data["shared"]["status"] = "unknown"
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_rejects_html(self):
        data = example_product()
        data["shared"]["name"] = "<script>"
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_rejects_extra_fields(self):
        data = example_product()
        data["shared"]["unexpected"] = "x"
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_rejects_bad_heading_position(self):
        data = example_product()
        data["packages"]["feature_headings"][1][
            "before_feature"
        ] = 99
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_rejects_duplicate_heading_position(self):
        data = example_product()
        data["packages"]["feature_headings"][1][
            "before_feature"
        ] = 0
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_does_not_mutate_input(self):
        data = example_product()
        original = copy.deepcopy(data)
        normalize_product_content(data)
        self.assertEqual(data, original)

    def test_preserves_multiline_statement(self):
        data = example_product()
        data["packages"]["top_statement_1"] = (
            "First line\nSecond line"
        )
        content = normalize_product_content(data)
        self.assertEqual(
            content["packages"]["top_statement_1"],
            "First line\nSecond line",
        )

    def test_rejects_price_line_break(self):
        data = example_product()
        data["shared"]["monthly_price"] = "$49\nmore"
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_rejects_blank_button_text(self):
        data = example_product()
        data["pricing"]["button_text"] = " "
        with self.assertRaises(MarketingContentError):
            normalize_product_content(data)

    def test_empty_feature_headings_allowed(self):
        data = example_product()
        data["packages"]["feature_headings"] = []
        content = normalize_product_content(data)
        self.assertEqual(
            content["packages"]["feature_headings"], []
        )


if __name__ == "__main__":
    unittest.main()
