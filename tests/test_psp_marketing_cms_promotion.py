import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
    normalize_home_promotion_content,
)


def valid_promotion():
    return {
        "promotion": {
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
                "Client Management",
                "Appointment Calendar",
                "PeachBook",
                "PeachWeb",
                "Income & Expenses",
                "Inventory",
                "Coach Peach",
                "Square Integration",
                "Import & Export",
            ],
        }
    }


class MarketingCMSPromotionTests(unittest.TestCase):

    def test_valid_promotion(self):
        result = normalize_home_promotion_content(
            valid_promotion()
        )
        self.assertEqual(
            result["promotion"]["monthly_price"],
            "$49",
        )
        self.assertEqual(
            len(result["promotion"]["features"]),
            9,
        )

    def test_preserves_manual_headline_line_breaks(self):
        result = normalize_home_promotion_content(
            valid_promotion()
        )
        self.assertEqual(
            result["promotion"]["headline"],
            "One business.\nOne owner.\nOne connected system.",
        )

    def test_normalizes_windows_line_feeds(self):
        payload = valid_promotion()
        payload["promotion"]["headline"] = "First\r\nSecond"
        result = normalize_home_promotion_content(payload)
        self.assertEqual(
            result["promotion"]["headline"],
            "First\nSecond",
        )

    def test_allows_natural_wrapping_without_manual_breaks(self):
        payload = valid_promotion()
        payload["promotion"]["headline"] = (
            "One business. One owner. One connected system."
        )
        result = normalize_home_promotion_content(payload)
        self.assertEqual(
            result["promotion"]["headline"],
            payload["promotion"]["headline"],
        )

    def test_rejects_missing_field(self):
        payload = valid_promotion()
        del payload["promotion"]["monthly_price"]
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_unsupported_field(self):
        payload = valid_promotion()
        payload["promotion"]["unexpected"] = "value"
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_html(self):
        payload = valid_promotion()
        payload["promotion"]["headline"] = "<script>alert(1)</script>"
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_control_characters(self):
        payload = valid_promotion()
        payload["promotion"]["headline"] = "First\tSecond"
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_excessive_headline_length(self):
        payload = valid_promotion()
        payload["promotion"]["headline"] = "A" * 241
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_excessive_headline_lines(self):
        payload = valid_promotion()
        payload["promotion"]["headline"] = "\n".join(
            ["Headline"] * 9
        )
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_missing_feature(self):
        payload = valid_promotion()
        payload["promotion"]["features"].pop()
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_rejects_invalid_feature(self):
        payload = valid_promotion()
        payload["promotion"]["features"][0] = "<b>Client</b>"
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content(payload)

    def test_does_not_modify_submitted_data(self):
        payload = valid_promotion()
        original = copy.deepcopy(payload)
        normalize_home_promotion_content(payload)
        self.assertEqual(payload, original)

    def test_rejects_other_content_sections(self):
        with self.assertRaises(MarketingContentError):
            normalize_home_promotion_content({
                "hero": {}
            })


if __name__ == "__main__":
    unittest.main()
