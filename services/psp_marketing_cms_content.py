"""Validation for Peach Suite Pro corporate marketing content.

Corporate CMS content is separate from customer PeachWeb settings.
Validation does not save, publish, or access the database.
"""

HOME_HERO_LIMITS = {
    "primary_button_text": 80,
    "secondary_button_text": 80,
    "pricing_sentence": 300,
}


class MarketingContentError(ValueError):
    """Invalid or unsupported marketing content."""


def normalize_home_content(payload):
    """Validate a complete Home Page hero-section snapshot."""

    if not isinstance(payload, dict):
        raise MarketingContentError(
            "Home Page content must be an object."
        )

    if set(payload) != {"hero"}:
        raise MarketingContentError(
            "Only the Home Page hero section is supported."
        )

    hero = payload["hero"]

    if not isinstance(hero, dict):
        raise MarketingContentError(
            "Hero content must be an object."
        )

    if set(hero) != set(HOME_HERO_LIMITS):
        raise MarketingContentError(
            "Hero content contains missing or unsupported fields."
        )

    normalized = {}

    for field, maximum in HOME_HERO_LIMITS.items():
        value = hero[field]

        if not isinstance(value, str):
            raise MarketingContentError(
                f"{field} must be text."
            )

        value = value.strip()

        if not value:
            raise MarketingContentError(
                f"{field} cannot be empty."
            )

        if len(value) > maximum:
            raise MarketingContentError(
                f"{field} exceeds its character limit."
            )

        if any(ord(character) < 32 for character in value):
            raise MarketingContentError(
                f"{field} contains control characters."
            )

        if "<" in value or ">" in value:
            raise MarketingContentError(
                f"{field} cannot contain HTML markup."
            )

        normalized[field] = value

    return {"hero": normalized}

HOME_PROMOTION_FIELDS = {
    "product_label": 80,
    "headline": 240,
    "monthly_price": 32,
    "pricing_description": 300,
}

HOME_PROMOTION_FEATURE_COUNT = 9


def normalize_home_promotion_content(payload):
    """Validate one independent Home Page promotion snapshot.

    The headline preserves intentional line feeds. The public
    template will handle automatic word wrapping separately.
    """
    if not isinstance(payload, dict) or set(payload) != {"promotion"}:
        raise MarketingContentError(
            "Home promotion content must contain only promotion."
        )

    promotion = payload["promotion"]

    if not isinstance(promotion, dict):
        raise MarketingContentError(
            "Promotion content must be an object."
        )

    required = set(HOME_PROMOTION_FIELDS) | {"features"}

    if set(promotion) != required:
        raise MarketingContentError(
            "Promotion contains missing or unsupported fields."
        )

    normalized = {}

    for field, maximum in HOME_PROMOTION_FIELDS.items():
        value = promotion[field]

        if not isinstance(value, str):
            raise MarketingContentError(
                f"{field} must be text."
            )

        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = value.strip()

        if not value or len(value) > maximum:
            raise MarketingContentError(
                f"{field} is empty or exceeds its character limit."
            )

        if any(
            ord(character) < 32 and character != "\n"
            for character in value
        ) or "\x7f" in value:
            raise MarketingContentError(
                f"{field} contains control characters."
            )

        if "<" in value or ">" in value:
            raise MarketingContentError(
                f"{field} cannot contain HTML markup."
            )

        if field == "headline":
            if len(value.split("\n")) > 8:
                raise MarketingContentError(
                    "Headline contains too many lines."
                )
        elif "\n" in value:
            raise MarketingContentError(
                f"{field} must be a single line."
            )

        normalized[field] = value

    features = promotion["features"]

    if (
        not isinstance(features, list)
        or len(features) != HOME_PROMOTION_FEATURE_COUNT
    ):
        raise MarketingContentError(
            "The Home promotion requires exactly nine features."
        )

    normalized_features = []

    for feature in features:
        if not isinstance(feature, str):
            raise MarketingContentError(
                "Every feature must be text."
            )

        feature = feature.strip()

        if not feature or len(feature) > 100:
            raise MarketingContentError(
                "A feature is empty or too long."
            )

        if any(ord(c) < 32 or ord(c) == 127 for c in feature):
            raise MarketingContentError(
                "Features cannot contain control characters."
            )

        if "<" in feature or ">" in feature:
            raise MarketingContentError(
                "Features cannot contain HTML markup."
            )

        normalized_features.append(feature)

    normalized["features"] = normalized_features

    return {"promotion": normalized}


def normalize_home_peachweb_content(payload):
    """Validate an independent PeachWeb showcase snapshot.

    No image is required while editing the initial draft.
    Cloudinary assets are identified by immutable public IDs.
    The caption preserves intentional newline characters.
    """
    import re
    from urllib.parse import urlsplit

    if not isinstance(payload, dict) or set(payload) != {"showcase"}:
        raise MarketingContentError(
            "PeachWeb content must contain only showcase."
        )

    showcase = payload["showcase"]

    if not isinstance(showcase, dict):
        raise MarketingContentError(
            "PeachWeb showcase must be an object."
        )

    fields = {
        "image_public_id",
        "image_url",
        "image_alt",
        "caption",
    }

    if set(showcase) != fields:
        raise MarketingContentError(
            "PeachWeb showcase contains missing or unsupported fields."
        )

    normalized = {}

    for field in fields:
        value = showcase[field]

        if not isinstance(value, str):
            raise MarketingContentError(
                f"{field} must be text."
            )

        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = value.strip()

        maximum = {
            "image_public_id": 180,
            "image_url": 600,
            "image_alt": 180,
            "caption": 350,
        }[field]

        if len(value) > maximum:
            raise MarketingContentError(
                f"{field} exceeds its character limit."
            )

        if any(
            ord(c) < 32 and not (field == "caption" and c == "\n")
            for c in value
        ) or "\x7f" in value:
            raise MarketingContentError(
                f"{field} contains control characters."
            )

        if field in {"image_alt", "caption"}:
            if "<" in value or ">" in value:
                raise MarketingContentError(
                    f"{field} cannot contain HTML markup."
                )

        normalized[field] = value

    public_id = normalized["image_public_id"]
    url = normalized["image_url"]
    alt = normalized["image_alt"]

    if bool(public_id) != bool(url):
        raise MarketingContentError(
            "The PeachWeb image ID and URL must be provided together."
        )

    if not public_id:
        if alt:
            raise MarketingContentError(
                "Image description requires an uploaded picture."
            )
        return {"showcase": normalized}

    if not alt:
        raise MarketingContentError(
            "An uploaded PeachWeb picture requires alt text."
        )

    expected_id = (
        r"peach-suite-pro/marketing-cms/showcases/"
        r"peachweb/[0-9a-f]{32}"
    )

    if re.fullmatch(expected_id, public_id) is None:
        raise MarketingContentError(
            "Invalid PeachWeb image identifier."
        )

    parsed = urlsplit(url)

    if (
        parsed.scheme != "https"
        or parsed.netloc != "res.cloudinary.com"
        or "/image/upload/" not in parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise MarketingContentError(
            "Invalid PeachWeb image URL."
        )

    if not any(
        parsed.path.endswith(f"/{public_id}.{ext}")
        for ext in ("png", "jpg")
    ):
        raise MarketingContentError(
            "PeachWeb image URL does not match its asset ID."
        )

    return {"showcase": normalized}


def normalize_home_peachbook_content(payload):
    """Validate an independent PeachBook showcase snapshot.

    No image is required while editing the initial draft.
    Cloudinary assets are identified by immutable public IDs.
    The caption preserves intentional newline characters.
    """
    import re
    from urllib.parse import urlsplit

    if not isinstance(payload, dict) or set(payload) != {"showcase"}:
        raise MarketingContentError(
            "PeachBook content must contain only showcase."
        )

    showcase = payload["showcase"]

    if not isinstance(showcase, dict):
        raise MarketingContentError(
            "PeachBook showcase must be an object."
        )

    fields = {
        "image_public_id",
        "image_url",
        "image_alt",
        "caption",
    }

    if set(showcase) != fields:
        raise MarketingContentError(
            "PeachBook showcase contains missing or unsupported fields."
        )

    normalized = {}

    for field in fields:
        value = showcase[field]

        if not isinstance(value, str):
            raise MarketingContentError(
                f"{field} must be text."
            )

        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = value.strip()

        maximum = {
            "image_public_id": 180,
            "image_url": 600,
            "image_alt": 180,
            "caption": 350,
        }[field]

        if len(value) > maximum:
            raise MarketingContentError(
                f"{field} exceeds its character limit."
            )

        if any(
            ord(c) < 32 and not (field == "caption" and c == "\n")
            for c in value
        ) or "\x7f" in value:
            raise MarketingContentError(
                f"{field} contains control characters."
            )

        if field in {"image_alt", "caption"}:
            if "<" in value or ">" in value:
                raise MarketingContentError(
                    f"{field} cannot contain HTML markup."
                )

        normalized[field] = value

    public_id = normalized["image_public_id"]
    url = normalized["image_url"]
    alt = normalized["image_alt"]

    if bool(public_id) != bool(url):
        raise MarketingContentError(
            "The PeachBook image ID and URL must be provided together."
        )

    if not public_id:
        if alt:
            raise MarketingContentError(
                "Image description requires an uploaded picture."
            )
        return {"showcase": normalized}

    if not alt:
        raise MarketingContentError(
            "An uploaded PeachBook picture requires alt text."
        )

    expected_id = (
        r"peach-suite-pro/marketing-cms/showcases/"
        r"peachbook/[0-9a-f]{32}"
    )

    if re.fullmatch(expected_id, public_id) is None:
        raise MarketingContentError(
            "Invalid PeachBook image identifier."
        )

    parsed = urlsplit(url)

    if (
        parsed.scheme != "https"
        or parsed.netloc != "res.cloudinary.com"
        or "/image/upload/" not in parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise MarketingContentError(
            "Invalid PeachBook image URL."
        )

    if not any(
        parsed.path.endswith(f"/{public_id}.{ext}")
        for ext in ("png", "jpg")
    ):
        raise MarketingContentError(
            "PeachBook image URL does not match its asset ID."
        )

    return {"showcase": normalized}
