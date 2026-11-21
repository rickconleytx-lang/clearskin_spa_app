"""Tests for independent marketing page introductions."""

import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_page_intro import (
    normalize_page_intro_content,
)


def example():
    return {
        "intro": {
            "heading": "Launch Special",
            "paragraph": "Use code LAUNCH10 to save.",
        }
    }


class PageIntroductionTests(unittest.TestCase):

    def test_packages_valid(self):
        result = normalize_page_intro_content(
            "packages.intro", example()
        )
        self.assertEqual(
            result["intro"]["heading"],
            "Launch Special",
        )

    def test_pricing_valid(self):
        result = normalize_page_intro_content(
            "pricing.intro", example()
        )
        self.assertEqual(
            result["intro"]["paragraph"],
            "Use code LAUNCH10 to save.",
        )

    def test_independent_page_content(self):
        packages = example()
        pricing = example()
        pricing["intro"]["heading"] = "Pricing Notice"

        a = normalize_page_intro_content(
            "packages.intro", packages
        )
        b = normalize_page_intro_content(
            "pricing.intro", pricing
        )
        self.assertNotEqual(
            a["intro"]["heading"],
            b["intro"]["heading"],
        )

    def test_trims_whitespace(self):
        data = example()
        data["intro"]["heading"] = "  Launch Special  "
        result = normalize_page_intro_content(
            "packages.intro", data
        )
        self.assertEqual(
            result["intro"]["heading"],
            "Launch Special",
        )

    def test_multiline_paragraph(self):
        data = example()
        data["intro"]["paragraph"] = "Line 1\r\nLine 2"
        result = normalize_page_intro_content(
            "pricing.intro", data
        )
        self.assertEqual(
            result["intro"]["paragraph"],
            "Line 1\nLine 2",
        )

    def test_rejects_unknown_section(self):
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "home.promo", example()
            )

    def test_rejects_extra_field(self):
        data = example()
        data["intro"]["extra"] = "Not supported"
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "pricing.intro", data
            )

    def test_rejects_empty_heading(self):
        data = example()
        data["intro"]["heading"] = " "
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "packages.intro", data
            )

    def test_rejects_empty_paragraph(self):
        data = example()
        data["intro"]["paragraph"] = ""
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "pricing.intro", data
            )

    def test_rejects_html(self):
        data = example()
        data["intro"]["paragraph"] = "<script>bad</script>"
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "packages.intro", data
            )

    def test_rejects_control_character(self):
        data = example()
        data["intro"]["heading"] = "Bad\x00Heading"
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "pricing.intro", data
            )

    def test_rejects_long_heading(self):
        data = example()
        data["intro"]["heading"] = "A" * 201
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "packages.intro", data
            )

    def test_rejects_long_paragraph(self):
        data = example()
        data["intro"]["paragraph"] = "A" * 1201
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "pricing.intro", data
            )

    def test_rejects_too_many_lines(self):
        data = example()
        data["intro"]["paragraph"] = "\n".join(
            ["Line"] * 11
        )
        with self.assertRaises(MarketingContentError):
            normalize_page_intro_content(
                "packages.intro", data
            )

    def test_does_not_mutate_input(self):
        data = example()
        original = copy.deepcopy(data)
        normalize_page_intro_content(
            "pricing.intro", data
        )
        self.assertEqual(data, original)


if __name__ == "__main__":
    unittest.main()
