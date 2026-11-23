"""Initial shared product content regression tests."""

import unittest

from services.psp_marketing_cms_product_baseline import (
    BASELINE_PRODUCTS,
    ORIGINAL_PUBLIC_CARD_REFERENCES,
    get_product_baseline,
)
from services.psp_marketing_cms_product_content import (
    normalize_product_content,
)
from services.psp_marketing_cms_product_features import (
    pricing_product_features,
)


class ProductBaselineTests(unittest.TestCase):

    def test_four_products(self):
        self.assertEqual(
            set(BASELINE_PRODUCTS),
            {"solo", "peachpos", "team", "collective"},
        )

    def test_each_snapshot_valid(self):
        for key in BASELINE_PRODUCTS:
            with self.subTest(product=key):
                content = get_product_baseline(key)
                self.assertEqual(
                    normalize_product_content(content),
                    content,
                )

    def test_existing_product_names(self):
        expected = {
            "solo": "🍑 Solo",
            "peachpos": "🍑 PeachPOS",
            "team": "👥 Team",
            "collective": "🍑 Peach Collective",
        }
        for key, name in expected.items():
            self.assertEqual(
                get_product_baseline(key)["shared"]["name"],
                name,
            )

    def test_original_feature_counts(self):
        expected = {
            "solo": (16, 10),
            "peachpos": (14, 10),
            "team": (14, 7),
            "collective": (15, 6),
        }
        for key, (packages_count, pricing_count) in expected.items():
            content = get_product_baseline(key)
            reference = ORIGINAL_PUBLIC_CARD_REFERENCES[key]
            self.assertEqual(
                len(content["shared"]["features"]),
                packages_count,
            )
            self.assertEqual(
                len(reference["pricing"]["features"]),
                pricing_count,
            )

    def test_pricing_uses_shared_first_ten(self):
        for key in BASELINE_PRODUCTS:
            features = get_product_baseline(key)["shared"]["features"]
            self.assertEqual(
                pricing_product_features(features),
                features[:10],
            )

    def test_provider_price_units(self):
        collective = get_product_baseline("collective")["shared"]
        self.assertEqual(collective["monthly_unit"], "/provider/month")
        self.assertEqual(collective["annual_unit"], "/provider/year")

    def test_original_prices(self):
        expected = {
            "solo": ("$49", "$490"),
            "peachpos": ("$49", "$490"),
            "team": ("$75", "$750"),
            "collective": ("$49", "$490"),
        }
        for key, (monthly, annual) in expected.items():
            shared = get_product_baseline(key)["shared"]
            self.assertEqual(
                (shared["monthly_price"], shared["annual_price"]),
                (monthly, annual),
            )

    def test_group_headings_retained(self):
        self.assertEqual(
            len(get_product_baseline("team")["packages"]["feature_headings"]),
            1,
        )
        headings = get_product_baseline(
            "collective"
        )["packages"]["feature_headings"]
        self.assertEqual(
            [item["before_feature"] for item in headings],
            [0, 8],
        )

    def test_solo_special_notes_retained(self):
        solo = get_product_baseline("solo")
        self.assertEqual(
            solo["packages"]["bottom_heading"],
            "Already have a website?",
        )
        self.assertEqual(
            solo["pricing"]["bottom_heading"],
            "10-day free trial.",
        )

    def test_original_pricing_lists_preserved_for_reference(self):
        for key in BASELINE_PRODUCTS:
            reference = ORIGINAL_PUBLIC_CARD_REFERENCES[key]
            self.assertTrue(reference["pricing"]["features"])
            self.assertEqual(
                len(reference["packages_sha256"]), 64
            )
            self.assertEqual(
                len(reference["pricing_sha256"]), 64
            )

    def test_baseline_returns_independent_copies(self):
        first = get_product_baseline("solo")
        first["shared"]["features"].clear()
        second = get_product_baseline("solo")
        self.assertEqual(len(second["shared"]["features"]), 16)

    def test_invalid_product_rejected(self):
        with self.assertRaises(KeyError):
            get_product_baseline("unknown")


if __name__ == "__main__":
    unittest.main()
