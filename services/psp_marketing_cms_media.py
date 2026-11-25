"""Validate marketing showcase screenshots before external upload.

No filesystem writes, network requests, or database operations.
"""

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 6000

SUPPORTED_SOURCE_FORMATS = frozenset({
    "PNG",
    "JPEG",
})


class MarketingCMSImageError(ValueError):
    """Invalid or unsupported Marketing CMS screenshot."""


def prepare_showcase_image(uploaded_file):
    """Validate and re-encode a screenshot for future upload.

    File extensions and browser-supplied MIME types are not trusted.
    Re-encoding removes original image metadata.
    """

    if (
        uploaded_file is None
        or not getattr(uploaded_file, "filename", "")
    ):
        raise MarketingCMSImageError(
            "Choose a PNG or JPEG screenshot."
        )

    stream = getattr(uploaded_file, "stream", None)

    if (
        stream is None
        or not callable(getattr(stream, "read", None))
    ):
        raise MarketingCMSImageError(
            "The screenshot upload is invalid."
        )

    try:
        stream.seek(0)
        raw = stream.read(MAX_UPLOAD_BYTES + 1)
    except (OSError, ValueError, TypeError) as exc:
        raise MarketingCMSImageError(
            "Unable to read the screenshot."
        ) from exc

    if not isinstance(raw, bytes) or not raw:
        raise MarketingCMSImageError(
            "The screenshot is empty or invalid."
        )

    if len(raw) > MAX_UPLOAD_BYTES:
        raise MarketingCMSImageError(
            "Screenshots must be 5 MB or smaller."
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )

            with Image.open(BytesIO(raw)) as probe:
                source_format = probe.format

                if source_format not in SUPPORTED_SOURCE_FORMATS:
                    raise MarketingCMSImageError(
                        "Only PNG and JPEG screenshots are supported."
                    )

                width, height = probe.size

                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_IMAGE_DIMENSION
                    or height > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise MarketingCMSImageError(
                        "Screenshot dimensions exceed the allowed limit."
                    )

                probe.verify()

            with Image.open(BytesIO(raw)) as original:
                original.load()

                cleaned = ImageOps.exif_transpose(original)

                try:
                    output = BytesIO()

                    if source_format == "JPEG":
                        cleaned.convert("RGB").save(
                            output,
                            format="JPEG",
                            quality=88,
                            optimize=True,
                        )

                        mime_type = "image/jpeg"
                        extension = ".jpg"

                    else:
                        has_alpha = (
                            "A" in cleaned.getbands()
                            or "transparency" in cleaned.info
                        )

                        cleaned.convert(
                            "RGBA" if has_alpha else "RGB"
                        ).save(
                            output,
                            format="PNG",
                            optimize=True,
                        )

                        mime_type = "image/png"
                        extension = ".png"

                finally:
                    cleaned.close()

    except MarketingCMSImageError:
        raise

    except (
        OSError,
        ValueError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise MarketingCMSImageError(
            "The screenshot could not be decoded safely."
        ) from exc

    data = output.getvalue()

    if not data or len(data) > MAX_OUTPUT_BYTES:
        raise MarketingCMSImageError(
            "The processed screenshot exceeds the allowed size."
        )

    return {
        "data": data,
        "content_type": mime_type,
        "extension": extension,
        "width": width,
        "height": height,
    }
