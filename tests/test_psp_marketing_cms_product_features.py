"""Tests for shared Packages/Pricing feature behavior."""

import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)

from services.psp_marketing_cms_product_features import (
    normalize_product_features,
    packages_product_features,
    pricing_product_features,
)


class ProductFeatureTests(unittest.TestCase):

    def test_packages_displays_all_sixteen(self):
        features = [f"Feature {i}" for i in range(1, 17)]
        self.assertEqual(
            packages_product_features(features),
            features,
        )

    def test_pricing_displays_first_ten(self):
        features = [f"Feature {i}" for i in range(1, 17)]
        self.assertEqual(
            pricing_product_features(features),
            features[:10],
        )

    def test_pricing_handles_fewer_than_ten(self):
        features = ["One", "Two", "Three"]
        self.assertEqual(
            pricing_product_features(features),
            features,
        )

    def test_exactly_ten(self):
        features = [f"Feature {i}" for i in range(10)]
        self.assertEqual(
            pricing_product_features(features),
            features,
        )

    def test_preserves_editor_order(self):
        features = ["Third", "First", "Second"]
        self.assertEqual(
            normalize_product_features(features),
            features,
        )

    def test_trims_surrounding_whitespace(self):
        self.assertEqual(
            normalize_product_features(["  Inventory  "]),
            ["Inventory"],
        )

    def test_does_not_modify_original_list(self):
        features = ["  Inventory  ", "Coach Peach"]
        normalize_product_features(features)
        self.assertEqual(
            features,
            ["  Inventory  ", "Coach Peach"],
        )

    def test_rejects_html(self):
        with self.assertRaises(MarketingContentError):
            normalize_product_features(["<script>test</script>"])

    def test_rejects_empty_entry(self):
        with self.assertRaises(MarketingContentError):
            normalize_product_features(["Valid", "   "])

    def test_rejects_control_characters(self):
        with self.assertRaises(MarketingContentError):
            normalize_product_features(["Invalid\nFeature"])

    def test_rejects_non_list(self):
        with self.assertRaises(MarketingContentError):
            normalize_product_features("Not a list")

    def test_rejects_more_than_one_hundred(self):
        features = ["Feature"] * 101
        with self.assertRaises(MarketingContentError):
            normalize_product_features(features)

    def test_empty_list_is_supported(self):
        self.assertEqual(
            pricing_product_features([]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
