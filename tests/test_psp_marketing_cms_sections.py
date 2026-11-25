"""Tests for independently versioned marketing section keys."""

from dataclasses import FrozenInstanceError
import unittest

from services.psp_marketing_cms_sections import (
    SECTION_REGISTRY,
    SURFACES,
    MarketingCMSSectionError,
    get_section_spec,
    sections_for_surface,
)


class MarketingCMSSectionsTests(unittest.TestCase):

    def test_eleven_independent_sections(self):
        self.assertEqual(len(SECTION_REGISTRY), 11)

    def test_legacy_home_key_preserved(self):
        spec = get_section_spec("home")
        self.assertEqual(spec.key, "home")
        self.assertEqual(spec.kind, "hero")

    def test_solo_shared_across_two_pages(self):
        self.assertEqual(
            get_section_spec("product.solo").surfaces,
            ("packages", "pricing"),
        )

    def test_other_products_shared_across_two_pages(self):
        for key in (
            "product.peachpos",
            "product.team",
            "product.collective",
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    get_section_spec(key).surfaces,
                    ("packages", "pricing"),
                )

    def test_showcases_only_on_home(self):
        for key in (
            "home.peachweb",
            "home.peachbook",
        ):
            with self.subTest(key=key):
                spec = get_section_spec(key)
                self.assertEqual(spec.kind, "showcase")
                self.assertEqual(spec.surfaces, ("home",))

    def test_benefits_shared(self):
        self.assertEqual(
            get_section_spec("marketing.benefits").surfaces,
            ("packages", "pricing"),
        )

    def test_home_page_sections(self):
        keys = {
            spec.key
            for spec in sections_for_surface("home")
        }
        self.assertEqual(
            keys,
            {
                "home",
                "home.peachweb",
                "home.peachbook",
                "home.promo",
            },
        )

    def test_home_promo_has_own_revision_identity(self):
        promo = get_section_spec("home.promo")
        solo = get_section_spec("product.solo")

        self.assertNotEqual(promo.key, solo.key)
        self.assertEqual(promo.kind, "promotion")
        self.assertEqual(promo.surfaces, ("home",))
        self.assertEqual(
            solo.surfaces,
            ("packages", "pricing"),
        )

    def test_home_page_does_not_duplicate_product_record(self):
        sections = sections_for_surface("home")

        self.assertEqual(
            sum(
                1 for section in sections
                if section.kind == "promotion"
            ),
            1,
        )

        self.assertFalse(
            any(
                section.kind == "product"
                for section in sections
            )
        )

    def test_packages_and_pricing_sections(self):
        expected = {
            "product.solo",
            "product.peachpos",
            "product.team",
            "product.collective",
            "marketing.benefits",
        }

        for surface in ("packages", "pricing"):
            with self.subTest(surface=surface):
                keys = {
                    spec.key
                    for spec in sections_for_surface(surface)
                }
                self.assertEqual(
                    keys,
                    expected | {f"{surface}.intro"},
                )

    def test_unknown_section_rejected(self):
        with self.assertRaises(MarketingCMSSectionError):
            get_section_spec("product.unapproved")

    def test_non_text_section_rejected(self):
        for key in (None, 1, True, []):
            with self.subTest(key=str(key)):
                with self.assertRaises(
                    MarketingCMSSectionError
                ):
                    get_section_spec(key)

    def test_unknown_surface_rejected(self):
        with self.assertRaises(MarketingCMSSectionError):
            sections_for_surface("admin")

    def test_registry_cannot_be_modified(self):
        with self.assertRaises(TypeError):
            SECTION_REGISTRY["product.new"] = object()

    def test_section_metadata_is_immutable(self):
        spec = get_section_spec("product.solo")
        with self.assertRaises(FrozenInstanceError):
            spec.key = "modified"

    def test_database_key_lengths_are_safe(self):
        self.assertEqual(len(SECTION_REGISTRY), len(set(SECTION_REGISTRY)))

        for key in SECTION_REGISTRY:
            with self.subTest(key=key):
                self.assertLessEqual(len(key), 80)
                self.assertTrue(key.isascii())

    def test_only_known_public_pages_are_used(self):
        for spec in SECTION_REGISTRY.values():
            self.assertTrue(spec.surfaces)
            self.assertTrue(
                set(spec.surfaces).issubset(SURFACES)
            )


if __name__ == "__main__":
    unittest.main()
