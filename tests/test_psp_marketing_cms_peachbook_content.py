import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
    normalize_home_peachbook_content,
)


def empty_content():
    return {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": "",
        }
    }


def image_content(extension="jpg"):
    content = empty_content()

    public_id = (
        "peach-suite-pro/marketing-cms/showcases/"
        "peachbook/" + "a" * 32
    )

    content["showcase"].update({
        "image_public_id": public_id,
        "image_url": (
            "https://res.cloudinary.com/example/"
            "image/upload/v1234567890/"
            f"{public_id}.{extension}"
        ),
        "image_alt": "Example PeachBook booking page",
        "caption": "Book appointments online.",
    })

    return content


class PeachBookContentTests(unittest.TestCase):

    def reject(self, content):
        with self.assertRaises(MarketingContentError):
            normalize_home_peachbook_content(content)

    def test_empty_showcase_allowed(self):
        content = empty_content()
        self.assertEqual(
            normalize_home_peachbook_content(content),
            content,
        )

    def test_valid_jpeg_image(self):
        content = image_content("jpg")
        result = normalize_home_peachbook_content(content)
        self.assertEqual(result, content)

    def test_valid_png_image(self):
        content = image_content("png")
        result = normalize_home_peachbook_content(content)
        self.assertEqual(result, content)

    def test_caption_preserves_line_breaks(self):
        content = empty_content()
        content["showcase"]["caption"] = (
            "Book online\r\nAnytime, anywhere."
        )
        result = normalize_home_peachbook_content(content)
        self.assertEqual(
            result["showcase"]["caption"],
            "Book online\nAnytime, anywhere.",
        )

    def test_input_not_mutated(self):
        content = image_content()
        original = copy.deepcopy(content)
        normalize_home_peachbook_content(content)
        self.assertEqual(content, original)

    def test_peachweb_image_namespace_rejected(self):
        content = image_content()
        for field in ("image_public_id", "image_url"):
            content["showcase"][field] = (
                content["showcase"][field]
                .replace("/peachbook/", "/peachweb/")
            )
        self.reject(content)

    def test_mismatched_image_url_rejected(self):
        content = image_content()
        content["showcase"]["image_url"] = (
            content["showcase"]["image_url"]
            .replace("a" * 32, "b" * 32)
        )
        self.reject(content)

    def test_untrusted_image_host_rejected(self):
        content = image_content()
        content["showcase"]["image_url"] = (
            content["showcase"]["image_url"]
            .replace("res.cloudinary.com", "example.com")
        )
        self.reject(content)

    def test_insecure_image_url_rejected(self):
        content = image_content()
        content["showcase"]["image_url"] = (
            content["showcase"]["image_url"]
            .replace("https://", "http://")
        )
        self.reject(content)

    def test_missing_image_description_rejected(self):
        content = image_content()
        content["showcase"]["image_alt"] = ""
        self.reject(content)

    def test_partial_image_reference_rejected(self):
        content = image_content()
        content["showcase"]["image_url"] = ""
        self.reject(content)

    def test_description_without_image_rejected(self):
        content = empty_content()
        content["showcase"]["image_alt"] = "Booking page"
        self.reject(content)

    def test_html_caption_rejected(self):
        content = image_content()
        content["showcase"]["caption"] = "<script>bad</script>"
        self.reject(content)

    def test_long_caption_rejected(self):
        content = image_content()
        content["showcase"]["caption"] = "A" * 351
        self.reject(content)

    def test_extra_fields_rejected(self):
        content = image_content()
        content["showcase"]["unapproved"] = "data"
        self.reject(content)

    def test_image_url_query_rejected(self):
        content = image_content()
        content["showcase"]["image_url"] += "?unexpected=1"
        self.reject(content)

    def test_unsupported_image_format_rejected(self):
        content = image_content("gif")
        self.reject(content)

    def test_non_text_field_rejected(self):
        content = empty_content()
        content["showcase"]["caption"] = None
        self.reject(content)


if __name__ == "__main__":
    unittest.main()
