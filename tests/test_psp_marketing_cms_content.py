import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
    normalize_home_content,
)


def valid_content():
    return {
        "hero": {
            "primary_button_text": "Start Your 10-Day Free Trial",
            "secondary_button_text": "View Pricing",
            "pricing_sentence": (
                "Solo is $49/month or $490/year "
                "after the 10-day free trial."
            ),
        }
    }


class MarketingContentTests(unittest.TestCase):

    def test_valid_home_content(self):
        result = normalize_home_content(valid_content())
        self.assertEqual(
            result["hero"]["secondary_button_text"],
            "View Pricing",
        )

    def test_trims_surrounding_whitespace(self):
        content = valid_content()
        content["hero"]["secondary_button_text"] = "  View Pricing  "
        result = normalize_home_content(content)
        self.assertEqual(
            result["hero"]["secondary_button_text"],
            "View Pricing",
        )

    def test_rejects_missing_field(self):
        content = valid_content()
        del content["hero"]["pricing_sentence"]
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_extra_field(self):
        content = valid_content()
        content["hero"]["unexpected_field"] = "Not allowed"
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_blank_text(self):
        content = valid_content()
        content["hero"]["primary_button_text"] = "   "
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_excessive_length(self):
        content = valid_content()
        content["hero"]["primary_button_text"] = "X" * 81
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_html(self):
        content = valid_content()
        content["hero"]["pricing_sentence"] = "<script>alert(1)</script>"
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_control_characters(self):
        content = valid_content()
        content["hero"]["primary_button_text"] = "Hello\nWorld"
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_non_text_values(self):
        content = valid_content()
        content["hero"]["secondary_button_text"] = 123
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)

    def test_rejects_other_page_sections(self):
        content = valid_content()
        content["pricing"] = {}
        with self.assertRaises(MarketingContentError):
            normalize_home_content(content)


if __name__ == "__main__":
    unittest.main()
