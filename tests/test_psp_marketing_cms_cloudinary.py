"""Offline tests for immutable marketing screenshot uploads."""

from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from PIL import Image

from services.psp_marketing_cms_cloudinary import (
    MEDIA_NAMESPACE,
    MarketingCMSStorageError,
    upload_showcase_image,
)
from services.psp_marketing_cms_media import (
    MarketingCMSImageError,
)


TOKEN = "a" * 32


def sample_upload(fmt="PNG"):
    output = BytesIO()

    Image.new(
        "RGB",
        (32, 18),
        (25, 95, 160),
    ).save(output, format=fmt)

    return SimpleNamespace(
        filename="sample.png",
        stream=BytesIO(output.getvalue()),
    )


def response(showcase="peachweb", token=TOKEN, fmt="png"):
    public_id = (
        f"{MEDIA_NAMESPACE}/{showcase}/{token}"
    )

    return {
        "public_id": public_id,
        "secure_url": (
            "https://res.cloudinary.com/demo/"
            "image/upload/v1763500000/"
            f"{public_id}.{fmt}"
        ),
        "resource_type": "image",
        "format": fmt,
    }


class MarketingCMSCloudinaryTests(unittest.TestCase):

    def test_peachweb_upload_never_overwrites(self):
        uploader = MagicMock(
            return_value=response()
        )

        stored = upload_showcase_image(
            sample_upload(),
            "peachweb",
            uploader=uploader,
            token_factory=lambda: TOKEN,
        )

        self.assertEqual(
            stored["public_id"],
            f"{MEDIA_NAMESPACE}/peachweb/{TOKEN}",
        )

        self.assertEqual(
            stored["content_type"],
            "image/png",
        )

        self.assertEqual(
            (stored["width"], stored["height"]),
            (32, 18),
        )

        args, kwargs = uploader.call_args

        self.assertFalse(kwargs["overwrite"])
        self.assertFalse(kwargs["unique_filename"])
        self.assertFalse(kwargs["use_filename"])
        self.assertEqual(
            kwargs["resource_type"],
            "image",
        )
        self.assertEqual(
            kwargs["public_id"],
            stored["public_id"],
        )

        with Image.open(args[0]) as image:
            self.assertEqual(image.format, "PNG")

    def test_peachbook_uses_separate_namespace(self):
        uploader = MagicMock(
            return_value=response("peachbook")
        )

        stored = upload_showcase_image(
            sample_upload(),
            "peachbook",
            uploader=uploader,
            token_factory=lambda: TOKEN,
        )

        self.assertIn(
            "/peachbook/",
            stored["public_id"],
        )

        self.assertNotIn(
            "/peachweb/",
            stored["public_id"],
        )

    def test_unique_tokens_create_distinct_ids(self):
        for token in ("b" * 32, "c" * 32):
            with self.subTest(token=token):
                uploader = MagicMock(
                    return_value=response(
                        token=token
                    )
                )

                stored = upload_showcase_image(
                    sample_upload(),
                    "peachweb",
                    uploader=uploader,
                    token_factory=lambda: token,
                )

                self.assertTrue(
                    stored["public_id"].endswith(token)
                )

    def test_invalid_showcase_never_uploads(self):
        uploader = MagicMock()

        with self.assertRaises(
            MarketingCMSImageError
        ):
            upload_showcase_image(
                sample_upload(),
                "other",
                uploader=uploader,
            )

        uploader.assert_not_called()

    def test_invalid_image_never_uploads(self):
        uploader = MagicMock()

        invalid = SimpleNamespace(
            filename="sample.png",
            stream=BytesIO(b"not an image"),
        )

        with self.assertRaises(
            MarketingCMSImageError
        ):
            upload_showcase_image(
                invalid,
                "peachweb",
                uploader=uploader,
            )

        uploader.assert_not_called()

    def test_invalid_token_never_uploads(self):
        uploader = MagicMock()

        with self.assertRaises(
            MarketingCMSStorageError
        ):
            upload_showcase_image(
                sample_upload(),
                "peachweb",
                uploader=uploader,
                token_factory=lambda: "../bad-id",
            )

        uploader.assert_not_called()

    def test_missing_public_id_rejected(self):
        result = response()
        result.pop("public_id")

        with self.assertRaises(
            MarketingCMSStorageError
        ):
            upload_showcase_image(
                sample_upload(),
                "peachweb",
                uploader=MagicMock(
                    return_value=result
                ),
                token_factory=lambda: TOKEN,
            )

    def test_insecure_url_rejected(self):
        result = response()
        result["secure_url"] = (
            result["secure_url"].replace(
                "https://", "http://"
            )
        )

        with self.assertRaises(
            MarketingCMSStorageError
        ):
            upload_showcase_image(
                sample_upload(),
                "peachweb",
                uploader=MagicMock(
                    return_value=result
                ),
                token_factory=lambda: TOKEN,
            )

    def test_untrusted_domain_rejected(self):
        result = response()
        result["secure_url"] = (
            result["secure_url"].replace(
                "res.cloudinary.com",
                "res.cloudinary.com.example.com",
            )
        )

        with self.assertRaises(
            MarketingCMSStorageError
        ):
            upload_showcase_image(
                sample_upload(),
                "peachweb",
                uploader=MagicMock(
                    return_value=result
                ),
                token_factory=lambda: TOKEN,
            )

    def test_mismatched_asset_url_rejected(self):
        result = response()
        result["secure_url"] = (
            result["secure_url"].replace(
                TOKEN,
                "f" * 32,
            )
        )

        with self.assertRaises(
            MarketingCMSStorageError
        ):
            upload_showcase_image(
                sample_upload(),
                "peachweb",
                uploader=MagicMock(
                    return_value=result
                ),
                token_factory=lambda: TOKEN,
            )

    def test_storage_failure_is_not_silently_ignored(self):
        uploader = MagicMock(
            side_effect=RuntimeError(
                "Simulated Cloudinary failure"
            )
        )

        with self.assertRaises(RuntimeError):
            upload_showcase_image(
                sample_upload(),
                "peachweb",
                uploader=uploader,
                token_factory=lambda: TOKEN,
            )


if __name__ == "__main__":
    unittest.main()
