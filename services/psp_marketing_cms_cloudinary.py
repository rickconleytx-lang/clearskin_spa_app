"""Immutable Cloudinary storage for corporate marketing screenshots.

Distinct from customer PeachWeb media. No image is overwritten
or deleted by this service.
"""

from io import BytesIO
import re
import secrets
from urllib.parse import urlsplit

from services.psp_marketing_cms_media import (
    MarketingCMSImageError,
    prepare_showcase_image,
)


SHOWCASE_TYPES = frozenset({
    "peachweb",
    "peachbook",
})

MEDIA_NAMESPACE = (
    "peach-suite-pro/marketing-cms/showcases"
)


class MarketingCMSStorageError(RuntimeError):
    """Unexpected or invalid media-storage response."""


def upload_showcase_image(
    uploaded_file,
    showcase,
    *,
    uploader=None,
    token_factory=None,
):
    """Validate and upload a new, non-overwriting showcase asset.

    The caller must authenticate and authorize Master Admin access
    before invoking this service.

    This service does not save database records, publish a revision,
    delete existing assets, or change customer PeachWeb images.
    """

    if showcase not in SHOWCASE_TYPES:
        raise MarketingCMSImageError(
            "Unsupported marketing showcase."
        )

    # Always decode and sanitize the original file first.
    prepared = prepare_showcase_image(uploaded_file)

    token = (
        token_factory()
        if token_factory is not None
        else secrets.token_hex(16)
    )

    if (
        not isinstance(token, str)
        or re.fullmatch(r"[0-9a-f]{32}", token) is None
    ):
        raise MarketingCMSStorageError(
            "Invalid generated media identifier."
        )

    public_id = (
        f"{MEDIA_NAMESPACE}/{showcase}/{token}"
    )

    image_format = (
        "png"
        if prepared["extension"] == ".png"
        else "jpg"
    )

    if uploader is None:
        import cloudinary.uploader
        uploader = cloudinary.uploader.upload

    result = uploader(
        BytesIO(prepared["data"]),
        public_id=public_id,
        resource_type="image",
        type="upload",
        format=image_format,
        overwrite=False,
        unique_filename=False,
        use_filename=False,
    )

    if not isinstance(result, dict):
        raise MarketingCMSStorageError(
            "Cloudinary returned an invalid response."
        )

    returned_id = result.get("public_id")
    secure_url = result.get("secure_url")

    if returned_id != public_id:
        raise MarketingCMSStorageError(
            "Cloudinary returned an unexpected asset ID."
        )

    if not isinstance(secure_url, str):
        raise MarketingCMSStorageError(
            "Cloudinary did not return a secure image URL."
        )

    parsed = urlsplit(secure_url)

    expected_suffix = (
        f"/{public_id}.{image_format}"
    )

    if (
        parsed.scheme != "https"
        or parsed.netloc != "res.cloudinary.com"
        or not parsed.path.endswith(expected_suffix)
        or parsed.query
        or parsed.fragment
    ):
        raise MarketingCMSStorageError(
            "Cloudinary returned an unexpected image URL."
        )

    if (
        result.get("resource_type", "image") != "image"
        or result.get("format", image_format)
        != image_format
    ):
        raise MarketingCMSStorageError(
            "Cloudinary returned an unexpected image format."
        )

    return {
        "showcase": showcase,
        "public_id": public_id,
        "secure_url": secure_url,
        "content_type": prepared["content_type"],
        "width": prepared["width"],
        "height": prepared["height"],
    }
