import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
    normalize_home_peachweb_content,
)


def empty_showcase():
    return {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": "",
        }
    }


def uploaded_showcase():
    content = empty_showcase()
    public_id = (
        "peach-suite-pro/marketing-cms/showcases/"
        "peachweb/" + "a" * 32
    )

    content["showcase"].update({
        "image_public_id": public_id,
        "image_url": (
            "https://res.cloudinary.com/psp/image/upload/"
            f"v1234567890/{public_id}.png"
        ),
        "image_alt": "Customer PeachWeb homepage",
        "caption": "Explore this PeachWeb website.",
    })

    return content


class PeachWebContentTests(unittest.TestCase):

    def test_empty_initial_showcase_is_valid(self):
        result = normalize_home_peachweb_content(
            empty_showcase()
        )
        self.assertEqual(result, empty_showcase())

    def test_uploaded_showcase_is_valid(self):
        result = normalize_home_peachweb_content(
            uploaded_showcase()
        )
        self.assertTrue(
            result["showcase"]["image_url"].startswith("https://")
        )

    def test_caption_preserves_actual_line_breaks(self):
        content = uploaded_showcase()
        content["showcase"]["caption"] = "First line\r\nSecond line"

        result = normalize_home_peachweb_content(content)

        self.assertEqual(
            result["showcase"]["caption"],
            "First line\nSecond line",
        )

    def test_surrounding_caption_whitespace_trimmed(self):
        content = uploaded_showcase()
        content["showcase"]["caption"] = "  PeachWeb customer  "

        result = normalize_home_peachweb_content(content)

        self.assertEqual(
            result["showcase"]["caption"],
            "PeachWeb customer",
        )

    def test_does_not_mutate_input(self):
        content = uploaded_showcase()
        original = copy.deepcopy(content)

        normalize_home_peachweb_content(content)
        self.assertEqual(content, original)

    def test_rejects_unsupported_fields(self):
        content = empty_showcase()
        content["showcase"]["unexpected"] = "value"

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_missing_fields(self):
        content = empty_showcase()
        del content["showcase"]["caption"]

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_partial_image_reference(self):
        content = uploaded_showcase()
        content["showcase"]["image_url"] = ""

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_image_without_alt_text(self):
        content = uploaded_showcase()
        content["showcase"]["image_alt"] = ""

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_wrong_showcase_namespace(self):
        content = uploaded_showcase()
        content["showcase"]["image_public_id"] = (
            content["showcase"]["image_public_id"]
            .replace("/peachweb/", "/peachbook/")
        )

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_untrusted_image_host(self):
        content = uploaded_showcase()
        content["showcase"]["image_url"] = (
            content["showcase"]["image_url"]
            .replace("res.cloudinary.com", "example.com")
        )

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_insecure_url(self):
        content = uploaded_showcase()
        content["showcase"]["image_url"] = (
            content["showcase"]["image_url"]
            .replace("https://", "http://")
        )

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_mismatched_image_url(self):
        content = uploaded_showcase()
        content["showcase"]["image_url"] = (
            content["showcase"]["image_url"]
            .replace(".png", ".gif")
        )

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_image_url_query(self):
        content = uploaded_showcase()
        content["showcase"]["image_url"] += "?unexpected=true"

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_markup_in_caption(self):
        content = uploaded_showcase()
        content["showcase"]["caption"] = "<script>bad</script>"

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_control_character_in_alt(self):
        content = uploaded_showcase()
        content["showcase"]["image_alt"] = "Bad\talt"

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_oversized_caption(self):
        content = uploaded_showcase()
        content["showcase"]["caption"] = "A" * 351

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)

    def test_rejects_non_text_fields(self):
        content = empty_showcase()
        content["showcase"]["caption"] = None

        with self.assertRaises(MarketingContentError):
            normalize_home_peachweb_content(content)


if __name__ == "__main__":
    unittest.main()
