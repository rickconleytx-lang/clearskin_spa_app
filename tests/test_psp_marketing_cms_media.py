"""Offline Marketing CMS image validation tests."""

from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from services import psp_marketing_cms_media as media


def upload(raw, filename="screenshot.png"):
    return SimpleNamespace(
        filename=filename,
        stream=BytesIO(raw),
    )


def image_bytes(fmt="PNG", *, mode="RGB"):
    out = BytesIO()

    Image.new(
        mode,
        (16, 9),
        (32, 100, 160),
    ).save(out, format=fmt)

    return out.getvalue()


class MarketingCMSMediaTests(unittest.TestCase):

    def test_png_decoded_and_reencoded(self):
        result = media.prepare_showcase_image(
            upload(image_bytes())
        )

        self.assertEqual(
            result["content_type"],
            "image/png",
        )

        self.assertEqual(
            result["extension"],
            ".png",
        )

        self.assertEqual(
            (result["width"], result["height"]),
            (16, 9),
        )

        with Image.open(BytesIO(result["data"])) as decoded:
            self.assertEqual(decoded.format, "PNG")

    def test_jpeg_decoded_and_reencoded(self):
        result = media.prepare_showcase_image(
            upload(
                image_bytes("JPEG"),
                "screenshot.jpg",
            )
        )

        self.assertEqual(
            result["content_type"],
            "image/jpeg",
        )

        self.assertEqual(
            result["extension"],
            ".jpg",
        )

        with Image.open(BytesIO(result["data"])) as decoded:
            self.assertEqual(decoded.format, "JPEG")

    def test_png_transparency_preserved(self):
        output = BytesIO()

        Image.new(
            "RGBA",
            (16, 9),
            (0, 40, 80, 70),
        ).save(output, "PNG")

        result = media.prepare_showcase_image(
            upload(output.getvalue())
        )

        with Image.open(BytesIO(result["data"])) as decoded:
            self.assertEqual(
                decoded.getpixel((0, 0))[3],
                70,
            )

    def test_png_metadata_removed(self):
        output = BytesIO()

        metadata = PngImagePlugin.PngInfo()

        metadata.add_text(
            "Comment",
            "Do not preserve this metadata",
        )

        Image.new(
            "RGB",
            (16, 9),
        ).save(
            output,
            "PNG",
            pnginfo=metadata,
        )

        result = media.prepare_showcase_image(
            upload(output.getvalue())
        )

        self.assertNotIn(
            b"Do not preserve",
            result["data"],
        )

    def test_filename_not_trusted(self):
        result = media.prepare_showcase_image(
            upload(
                image_bytes("PNG"),
                "../../arbitrary.jpg",
            )
        )

        self.assertEqual(
            result["extension"],
            ".png",
        )

        self.assertNotIn(
            "filename",
            result,
        )

    def test_missing_upload_rejected(self):
        with self.assertRaises(media.MarketingCMSImageError):
            media.prepare_showcase_image(None)

    def test_empty_filename_rejected(self):
        with self.assertRaises(media.MarketingCMSImageError):
            media.prepare_showcase_image(
                upload(image_bytes(), "")
            )

    def test_empty_image_rejected(self):
        with self.assertRaises(media.MarketingCMSImageError):
            media.prepare_showcase_image(upload(b""))

    def test_invalid_image_bytes_rejected(self):
        with self.assertRaises(media.MarketingCMSImageError):
            media.prepare_showcase_image(
                upload(b"not an image")
            )

    def test_gif_rejected(self):
        with self.assertRaisesRegex(
            media.MarketingCMSImageError,
            "Only PNG and JPEG",
        ):
            media.prepare_showcase_image(
                upload(
                    image_bytes("GIF"),
                    "animated.gif",
                )
            )

    def test_svg_rejected(self):
        with self.assertRaises(media.MarketingCMSImageError):
            media.prepare_showcase_image(
                upload(
                    b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                    "x.svg",
                )
            )

    def test_oversized_file_rejected(self):
        with self.assertRaisesRegex(
            media.MarketingCMSImageError,
            "5 MB or smaller",
        ):
            media.prepare_showcase_image(
                upload(
                    b"x" * (media.MAX_UPLOAD_BYTES + 1)
                )
            )

    def test_excess_pixel_count_rejected(self):
        with patch.object(
            media,
            "MAX_IMAGE_PIXELS",
            100,
        ):
            with self.assertRaisesRegex(
                media.MarketingCMSImageError,
                "dimensions",
            ):
                media.prepare_showcase_image(
                    upload(image_bytes())
                )

    def test_processed_size_limit_enforced(self):
        with patch.object(
            media,
            "MAX_OUTPUT_BYTES",
            1,
        ):
            with self.assertRaisesRegex(
                media.MarketingCMSImageError,
                "processed screenshot",
            ):
                media.prepare_showcase_image(
                    upload(image_bytes())
                )


if __name__ == "__main__":
    unittest.main()
